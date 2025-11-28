# views.py

import logging
import re
from typing import Any, Dict, List
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.db import transaction
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from . import constants as C
from .helper.views_helper import AppError, json_fail, json_ok
from .models import (
    VoiceConversation,
    TechnicalAssessment,
    AssessmentQuestion,
    AssessmentQuestionBank,
    CandidateAnswer,
    InterviewForm,
    InterviewQuestion,
)
from .views_schema_ import (
    AssessmentExtractor,
    OpenAIClient,
    QuestionIntentSummarizer,
    RoleQuestionGenerator,
    get_object_or_fail,
    handle_view_errors,
    safe_json_parse,
    validate_field,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

ASSESSMENT_TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
TARGET_ASSESSMENT_QUESTIONS = 3
ROLE_FALLBACK_TEMPLATES = [
    "Walk me through a recent {role} project you delivered. What problem did it solve and what stack did you use?",
    "How do you ensure quality and performance when building {role} features end-to-end?",
    "Describe a tough technical challenge you faced in {role} work and how you approached it.",
    "Which tools or frameworks are indispensable for you in {role}, and why?",
]


# ============================================================================
# Token Management
# ============================================================================


class AssessmentTokenManager:
    """Handles secure token generation and validation."""

    def __init__(self):
        self.signer = TimestampSigner()

    def encrypt(self, assessment_id: str) -> str:
        return self.signer.sign(str(assessment_id))

    def decrypt(
        self, token: str, max_age: int = ASSESSMENT_TOKEN_MAX_AGE
    ) -> str | None:
        try:
            return self.signer.unsign(token, max_age=max_age)
        except (BadSignature, SignatureExpired) as e:
            logger.warning(f"Invalid assessment token: {e}")
            return None


token_manager = AssessmentTokenManager()


# ============================================================================
# Verification Schema Helpers
# ============================================================================

SLUG_PATTERN = re.compile(r"[^a-z0-9_]+")
QUESTION_PREFIXES = [
    "what is your",
    "what's your",
    "what are your",
    "what are the",
    "what is the",
    "what's the",
    "what would be your",
    "what would you say is your",
    "what are you",
    "what kind of",
    "what types of",
    "tell me about your",
    "tell us about your",
    "tell me about the",
    "tell us about the",
    "can you describe your",
    "can you describe the",
    "describe your",
    "describe the",
    "do you have any",
]
STOPWORDS = {
    "your",
    "the",
    "any",
    "of",
    "for",
    "you",
    "about",
    "please",
    "kind",
    "type",
    "types",
    "are",
    "is",
    "do",
    "can",
    "tell",
    "me",
    "us",
}
QUESTION_INTENT_CACHE: dict[str, dict[str, Any]] = {}

BASE_VERIFICATION_FIELDS: list[dict[str, Any]] = [
    {
        "key": "name",
        "label": "Full name",
        "placeholder": "Your full name",
        "description": "Candidate's full name as stated during the interview",
        "required": True,
        "type": "text",
        "input_type": "text",
        "source": "profile",
    },
    {
        "key": "qualification",
        "label": "Qualification",
        "placeholder": "Your highest qualification",
        "description": "Highest qualification (degree, specialization, graduation year)",
        "required": True,
        "type": "text",
        "input_type": "text",
        "source": "profile",
    },
    {
        "key": "experience",
        "label": "Years of experience",
        "placeholder": "Total years of relevant experience",
        "description": "Total years of relevant professional experience",
        "required": True,
        "type": "text",
        "input_type": "text",
        "source": "profile",
    },
]


def slugify_field_key(value: str, fallback: str = "field") -> str:
    """Convert arbitrary text into a safe snake_case key."""
    if not value:
        value = fallback

    value = value.strip().lower()
    value = re.sub(r"[\s\-]+", "_", value)
    value = SLUG_PATTERN.sub("", value)
    value = re.sub(r"_+", "_", value).strip("_")

    if not value:
        value = fallback

    if value[0].isdigit():
        value = f"field_{value}"

    return value


def fallback_question_label(text: str) -> str:
    """Derive a short label from the original question text."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"[\?\.:]+$", "", cleaned)
    if len(cleaned) > 70:
        cleaned = cleaned[:67].rsplit(" ", 1)[0] + "..."
    return cleaned or "Response"


def strip_question_prefix(text: str) -> str:
    lowered = text.lower()
    for prefix in QUESTION_PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text.strip()


def derive_concept_label(question_text: str) -> str:
    """Heuristic fallback to convert a question into a short noun phrase."""
    working = strip_question_prefix(question_text)
    working = re.sub(r"[^\w\s]", " ", working).lower()
    words = [word for word in working.split() if word]
    filtered = [w for w in words if w not in STOPWORDS]
    candidates = filtered or words
    if not candidates:
        return fallback_question_label(question_text)
    concept_words = candidates[:4]
    return " ".join(word.capitalize() for word in concept_words)


def normalize_field_label(question_text: str, metadata_label: str | None) -> str:
    """Enforce concise title-style labels, falling back to heuristics if needed."""
    candidate = (metadata_label or "").strip()
    question_clean = (question_text or "").strip()

    if not candidate:
        candidate = derive_concept_label(question_clean)

    normalized = re.sub(r"[\?\.:]+$", "", candidate).strip()
    normalized = re.sub(r"\s+", " ", normalized)

    # If the model simply echoed the question or produced a very long label, fall back.
    if (
        not normalized
        or len(normalized) > 40
        or normalized.lower() == question_clean.lower()
        or normalized.count(" ") >= 5
    ):
        normalized = derive_concept_label(question_clean)

    return normalized


def ensure_unique_key(base_key: str, used_keys: set[str]) -> str:
    """Ensure generated keys remain unique within the schema."""
    key = base_key
    suffix = 2
    while key in used_keys:
        key = f"{base_key}_{suffix}"
        suffix += 1
    used_keys.add(key)
    return key


def summarize_question_intents(
    interview: InterviewForm, questions: list[InterviewQuestion]
) -> dict[str, dict[str, str]]:
    """Use the LLM-driven summarizer with lightweight caching."""
    cache_key = str(interview.id)
    freshness_token = f"{interview.updated_at.timestamp()}:{len(questions)}"

    cached = QUESTION_INTENT_CACHE.get(cache_key)
    if cached and cached.get("token") == freshness_token:
        return cached["data"]

    summarizer = QuestionIntentSummarizer()
    payload = [
        {
            "id": str(question.id),
            "question": question.question_text.strip(),
            "sequence": question.sequence_number,
        }
        for question in questions
        if question.question_text and question.question_text.strip()
    ]

    summaries = summarizer.summarize(payload)
    QUESTION_INTENT_CACHE[cache_key] = {"token": freshness_token, "data": summaries}
    return summaries


def duplicate_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a shallow copy of field definitions to avoid mutation."""
    return [field.copy() for field in fields]


def normalize_question_list(source: list[Any] | None) -> list[str]:
    """Convert arbitrary frontend payload into a clean list of strings."""
    if not isinstance(source, list):
        return []

    cleaned: list[str] = []
    for item in source:
        text = ""
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = (
                item.get("text")
                or item.get("question")
                or item.get("label")
                or ""
            )
            text = str(text).strip()
        else:
            text = str(item).strip()

        if text:
            cleaned.append(text)

    return cleaned


def build_question_field(
    question: InterviewQuestion, metadata: dict[str, Any], used_keys: set[str]
) -> dict[str, Any]:
    """Create a verification field descriptor for a specific interview question."""
    label = normalize_field_label(question.question_text, metadata.get("label"))
    description = metadata.get("summary") or question.question_text.strip()
    raw_key = metadata.get("key") or label
    slug = slugify_field_key(raw_key, fallback=f"question_{question.sequence_number}")
    key = ensure_unique_key(slug, used_keys)
    return {
        "key": key,
        "label": label,
        "placeholder": "Confirm the candidate's answer",
        "description": description,
        "sequence_number": question.sequence_number,
        "question_id": str(question.id),
        "helper_text": question.question_text.strip(),
        "required": True,
        "type": "textarea",
        "input_type": "text",
        "source": "question",
    }


def build_verification_fields(interview: InterviewForm | None) -> list[dict[str, Any]]:
    """Compose verification field metadata for the given interview."""
    fields = duplicate_fields(BASE_VERIFICATION_FIELDS)

    if not interview:
        return fields

    ordered_questions = list(interview.ordered_questions())
    question_summaries = summarize_question_intents(interview, ordered_questions)
    used_keys = {field["key"] for field in fields}

    for question in ordered_questions:
        metadata = question_summaries.get(str(question.id), {})
        fields.append(build_question_field(question, metadata, used_keys))

    return fields


def get_verification_schema(
    interview: InterviewForm | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return field metadata and extraction keys for verification."""
    fields = build_verification_fields(interview)
    keys = [field["key"] for field in fields]
    return fields, keys


# ============================================================================
# Helper Functions
# ============================================================================


def build_session_payload(request) -> dict:
    """Build session payload based on request type and assessment mode."""
    payload = C.get_session_payload()
    payload["instructions"] = C.build_default_voice_instructions()
    body = safe_json_parse(request.body) if request.method == "POST" else {}
    assessment_mode = bool(body.get("assessment_mode"))
    frontend_questions = (
        normalize_question_list(body.get("questions")) if assessment_mode else []
    )
    logger.info(
        "[SESSION] Incoming session request. Method=%s, assessment=%s, interview_id=%s",
        request.method,
        assessment_mode,
        request.GET.get("interview_id") or body.get("interview_id"),
    )

    interview_id = request.GET.get("interview_id") or body.get("interview_id")
    interview = None
    interview_questions: list[str] | None = None
    verification_fields, extraction_keys = get_verification_schema(None)

    if interview_id:
        logger.info(f"[SESSION] Requested interview_id={interview_id}")
        interview = (
            InterviewForm.objects.prefetch_related("questions")
            .filter(id=interview_id)
            .first()
        )
        if interview:
            verification_fields, extraction_keys = get_verification_schema(interview)
            interview_questions = interview.question_texts()
            logger.info(
                f"[SESSION] Using interview {interview.id} with "
                f"{len(interview_questions)} questions"
            )
            payload["instructions"] = C.build_interview_instructions(interview)
        else:
            logger.warning("Interview %s not found for session payload", interview_id)

    if assessment_mode:
        qualification = body.get("qualification", "")
        experience = body.get("experience", "")

        if frontend_questions:
            logger.info(
                "[SESSION][ASSESSMENT] Using %d question(s) from frontend payload",
                len(frontend_questions),
            )

        questions_for_persona = frontend_questions or []
        if not questions_for_persona and interview_questions:
            logger.warning(
                "[SESSION][ASSESSMENT] Frontend question payload empty; "
                "falling back to interview template (%d questions)",
                len(interview_questions),
            )
            questions_for_persona = interview_questions

        if not questions_for_persona:
            raise AppError(
                "Assessment questions are missing. Reopen the interview builder and retry.",
                status=400,
            )

        payload["instructions"] = C.get_assessment_persona(
            qualification,
            experience,
            questions=questions_for_persona,
        )
        logger.info(
            "[SESSION][ASSESSMENT] Built persona for %s/%s with %d questions",
            qualification,
            experience,
            len(questions_for_persona),
        )
        payload.pop("tools", None)
        payload.pop("tool_choice", None)
    else:
        payload["tools"] = [C.build_verify_tool(verification_fields)]
        payload["tool_choice"] = "auto"
        logger.info(
            "[SESSION] Attached verify tool with %d fields (%s)",
            len(extraction_keys),
            ", ".join(extraction_keys),
        )

    instructions_preview = " ".join(
        (payload.get("instructions") or "").splitlines()
    )[:200]
    logger.info(
        "[SESSION] Payload summary -> instructions_len=%d preview='%s...' tools=%s tool_choice=%s",
        len(payload.get("instructions") or ""),
        instructions_preview,
        [tool.get("name") for tool in payload.get("tools", [])],
        payload.get("tool_choice"),
    )

    return payload


def clean_verified_data(
    data: Dict[str, Any] | None, allowed_keys: list[str]
) -> Dict[str, str]:
    """Normalize user-provided verification overrides."""
    if not isinstance(data, dict) or not allowed_keys:
        return {}

    cleaned: Dict[str, str] = {}
    for field in allowed_keys:
        value = data.get(field)
        if value is None:
            continue

        text = str(value).strip()
        if text:
            cleaned[field] = text
    return cleaned


def humanize_field_label(key: str) -> str:
    """Convert machine keys into human readable labels."""
    if not key:
        return "Field"
    label = re.sub(r"[_\-]+", " ", key).strip()
    return label.title() if label else key


def get_field_label_map(
    interview: InterviewForm | None,
) -> dict[str, str]:
    """Build a key->label map for template and API rendering."""
    schema_fields, _ = get_verification_schema(interview)
    label_map = {}
    for field in schema_fields:
        label_map[field["key"]] = field.get("label") or humanize_field_label(field["key"])
    return label_map


def build_display_fields(conversation: VoiceConversation) -> list[dict[str, Any]]:
    """Materialize display-ready fields for response templates."""
    info = conversation.extracted_info or {}
    if not info:
        return []

    label_map = get_field_label_map(conversation.interview_form)
    display_fields: list[dict[str, Any]] = []
    for key, value in info.items():
        display_fields.append(
            {
                "key": key,
                "label": label_map.get(key) or humanize_field_label(key),
                "value": value,
            }
        )
    return display_fields


def build_role_fallback_questions(role: str, count: int = TARGET_ASSESSMENT_QUESTIONS) -> list[str]:
    """Provide deterministic fallback questions when LLM is unavailable."""
    label = role or "this role"
    questions: list[str] = []
    for template in ROLE_FALLBACK_TEMPLATES:
        question = template.format(role=label)
        if question in questions:
            continue
        questions.append(question)
        if len(questions) >= count:
            break

    if not questions:
        questions = [
            f"Describe your most impactful project related to {label}.",
            f"What tools or frameworks define your work in {label}?",
            f"Share a technical challenge you solved while working in {label}.",
        ]
    return questions


# ============================================================================
# Page Views
# ============================================================================


def interview_builder(request):
    """Render interview creation and listing page."""
    interviews_queryset = InterviewForm.objects.prefetch_related("questions").order_by(
        "-updated_at"
    )
    interviews = list(interviews_queryset)
    print(f"[INTERVIEW_BUILDER] Loaded {len(interviews)} interviews")

    return render(
        request,
        "form_ai/interviews.html",
        {
            "interviews": interviews,
            "existing_count": len(interviews),
        },
    )


def voice_page(request, interview_id: str | None = None):
    """Render the main voice assistant interface."""
    if not interview_id:
        return redirect("interview_builder")

    interview = get_object_or_fail(
        InterviewForm.objects.prefetch_related("questions"), id=interview_id
    )

    questions = [
        {"number": idx, "text": text}
        for idx, text in enumerate(interview.question_texts(), start=1)
    ]

    verification_fields, _ = get_verification_schema(interview)

    print(f"[VOICE_PAGE] Loaded interview {interview.id} for realtime session")

    return render(
        request,
        "form_ai/voice.html",
        {
            "interview": interview,
            "interview_id": str(interview.id),
            "questions": questions,
            "verification_fields": verification_fields,
        },
    )


def view_responses(request):
    """Display all conversation responses in a list view."""
    conversations_queryset = (
        VoiceConversation.objects.filter(extracted_info__isnull=False)
        .exclude(extracted_info={})
        .select_related("interview_form")
        .prefetch_related(
            "assessments", "assessments__questions", "assessments__questions__answer"
        )
    )

    conversations = list(conversations_queryset)
    for conversation in conversations:
        conversation.display_fields = build_display_fields(conversation)

    return render(request, "form_ai/responses.html", {"conversations": conversations})


def conduct_assessment(request, token: str):
    """Render assessment page using encrypted token."""
    assessment_id = token_manager.decrypt(token)

    if not assessment_id:
        return render(
            request,
            "form_ai/error.html",
            {
                "error": "Invalid or expired assessment link",
                "message": "This assessment link is no longer valid.",
            },
            status=400,
        )

    assessment = get_object_or_fail(
        TechnicalAssessment.objects.select_related(
            "conversation", "interview_form", "conversation__interview_form"
        ).prefetch_related("questions"),
        id=assessment_id,
    )

    questions_list = [
        {"number": q.sequence_number, "text": q.question_text}
        for q in assessment.questions.all()
    ]

    interview = assessment.interview_form or assessment.conversation.interview_form

    context = {
        "assessment": assessment,
        "assessment_id": str(assessment.id),
        "user_info": assessment.conversation.extracted_info,
        "questions": questions_list,
        "interview_id": str(interview.id) if interview else "",
        "interview_title": interview.title if interview else "",
    }

    return render(request, "form_ai/assessment.html", context)


# ============================================================================
# Realtime Session
# ============================================================================


@csrf_exempt
@require_http_methods(["GET", "POST"])
@handle_view_errors("Failed to create session")
def create_realtime_session(request):
    """Create OpenAI realtime session."""
    client = OpenAIClient()
    payload = build_session_payload(request)
    session_data = client.create_realtime_session(payload)
    return json_ok(session_data)


# ============================================================================
# Interview Management
# ============================================================================


@csrf_exempt
@require_POST
@handle_view_errors("Failed to create interview")
@transaction.atomic
def create_interview(request):
    """Create interview form with its ordered questions."""
    body = safe_json_parse(request.body)
    print(f"[CREATE_INTERVIEW] Raw payload: {body}")

    title = validate_field(body, "title", str)
    if not title or not title.strip():
        raise AppError("Interview title is required", status=400)

    questions = validate_field(body, "questions", list)
    cleaned_questions = [
        str(item).strip()
        for item in questions
        if isinstance(item, str) and item.strip()
    ]

    if not cleaned_questions:
        raise AppError("Add at least one interview question", status=400)

    interview = InterviewForm.objects.create(
        title=title.strip(),
        role=(body.get("role") or "").strip(),
        summary=(body.get("summary") or "").strip(),
        ai_prompt=(body.get("ai_prompt") or "").strip(),
    )

    InterviewQuestion.objects.bulk_create(
        [
            InterviewQuestion(
                form=interview,
                sequence_number=index,
                question_payload=InterviewQuestion.build_payload(text),
            )
            for index, text in enumerate(cleaned_questions, start=1)
        ]
    )

    redirect_path = reverse("voice_page", args=[interview.id])
    redirect_url = request.build_absolute_uri(redirect_path)
    print(
        f"[CREATE_INTERVIEW] Created interview {interview.id} "
        f"({len(cleaned_questions)} questions)"
    )

    return json_ok(
        {
            "interview_id": str(interview.id),
            "question_count": len(cleaned_questions),
            "redirect_url": redirect_url,
        },
        status=201,
    )


@csrf_exempt
@require_http_methods(["DELETE"])
@handle_view_errors("Failed to delete interview")
@transaction.atomic
def delete_interview(request, interview_id: str):
    """Delete an entire interview form and its questions."""
    interview = get_object_or_fail(
        InterviewForm.objects.prefetch_related("questions"), id=interview_id
    )

    question_count = interview.questions.count()
    title = interview.title
    interview.delete()

    remaining = InterviewForm.objects.count()

    logger.info(
        "[INTERVIEW] Deleted interview %s (%s) with %d questions",
        interview_id,
        title,
        question_count,
    )

    return json_ok(
        {
            "interview_id": str(interview_id),
            "title": title,
            "deleted_questions": question_count,
            "remaining_interviews": remaining,
        }
    )


@csrf_exempt
@require_http_methods(["DELETE"])
@handle_view_errors("Failed to delete interview question")
@transaction.atomic
def delete_interview_question(request, question_id: int):
    """Delete a single interview question and resequence the remainder."""
    question = get_object_or_fail(
        InterviewQuestion.objects.select_related("form"), id=question_id
    )
    form = question.form

    if form.questions.count() <= 1:
        raise AppError(
            "At least one question is required per interview. Add another question before deleting this one.",
            status=400,
        )

    print(
        f"[DELETE_QUESTION] Removing Q{question.sequence_number} "
        f"from interview {form.id}"
    )
    question.delete()

    # Resequence remaining questions for consistent ordering
    remaining = form.questions.order_by("sequence_number", "id")
    for idx, item in enumerate(remaining, start=1):
        if item.sequence_number != idx:
            InterviewQuestion.objects.filter(id=item.id).update(sequence_number=idx)

    return json_ok(
        {
            "interview_id": str(form.id),
            "question_id": question_id,
            "remaining_questions": remaining.count(),
        }
    )


# ============================================================================
# Conversation Management
# ============================================================================


@csrf_exempt
@require_POST
@handle_view_errors("Failed to save conversation")
def save_conversation(request):
    """Save conversation messages to database."""
    body = safe_json_parse(request.body)
    messages = validate_field(body, "messages", list)
    session_id = body.get("session_id")
    interview_form = None

    interview_id = body.get("interview_id")
    if interview_id:
        interview_form = get_object_or_fail(InterviewForm, id=interview_id)

    conversation = VoiceConversation.objects.create(
        session_id=session_id,
        messages=messages,
        interview_form=interview_form,
    )

    logger.info(
        "[CONVERSATION] Saved conversation %s with %d messages",
        conversation.pk,
        len(messages),
    )

    return json_ok(
        {
            "conversation_id": conversation.pk,
            "session_id": session_id,
            "interview_id": str(interview_form.id) if interview_form else None,
            "created_at": conversation.created_at.isoformat(),
        }
    )


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
def analyze_conversation(request):
    """Analyze conversation and extract structured user data."""
    body = safe_json_parse(request.body)
    session_id = validate_field(body, "session_id", str)

    conversation = get_object_or_fail(VoiceConversation, session_id=session_id)
    schema_fields, extraction_keys = get_verification_schema(conversation.interview_form)
    overrides = clean_verified_data(body.get("verified_data"), extraction_keys)

    client = OpenAIClient()
    extracted_data = client.extract_structured_data(
        conversation.messages, schema_fields
    )

    if overrides:
        extracted_data.update(overrides)
        logger.info(
            "[CONVERSATION] Applied verified overrides for session %s: %s",
            session_id,
            overrides,
        )

    conversation.extracted_info = extracted_data
    conversation.save(update_fields=["extracted_info", "updated_at"])

    logger.info(
        "[CONVERSATION] Analysis complete for %s (%s)",
        conversation.pk,
        ", ".join(extracted_data.keys()),
    )

    return json_ok(
        {
            "session_id": session_id,
            "conversation_id": conversation.pk,
            "user_response": extracted_data,
        }
    )


# ============================================================================
# Assessment Management
# ============================================================================


@csrf_exempt
@require_POST
@handle_view_errors("Failed to generate assessment")
@transaction.atomic
def generate_assessment(request, conv_id: int):
    """Generate assessment with role-specific technical questions."""
    conversation = get_object_or_fail(
        VoiceConversation.objects.select_related("interview_form"), id=conv_id
    )

    logger.info(
        f"[GENERATE] Conversation {conv_id}, extracted_info: {conversation.extracted_info}"
    )

    if not conversation.extracted_info:
        logger.error(f"[GENERATE] No extracted_info for conversation {conv_id}")
        return json_fail(
            "No user data available. Please complete the voice interview first.",
            status=400,
        )

    interview_form = conversation.interview_form
    if not interview_form:
        logger.error("[GENERATE] Conversation %s missing interview reference", conv_id)
        return json_fail(
            "Interview reference missing. Please create a new voice interview from the builder.",
            status=400,
        )

    # Get role from interview form
    role = (interview_form.role or interview_form.title or "").strip()
    target_count = TARGET_ASSESSMENT_QUESTIONS

    # Use stored questions as examples but prefer dynamic generation per role
    seeded_examples = C.get_assessment_questions_for_role(role)
    template_examples = seeded_examples or C.get_question_template_samples(5)

    generator = RoleQuestionGenerator()
    questions_list = generator.generate(role, template_examples, count=target_count)

    if questions_list:
        logger.info(
            "[GENERATE] Generated %d AI questions for role '%s'",
            len(questions_list),
            role,
        )
    else:
        logger.warning(
            "[GENERATE] AI question generator returned no results for role '%s'",
            role,
        )
        questions_list = []

    def extend_questions(source: list[str]):
        if not source:
            return
        for item in source:
            text = (item or "").strip()
            if not text:
                continue
            if text in questions_list:
                continue
            questions_list.append(text)
            if len(questions_list) >= target_count:
                break

    if len(questions_list) < target_count:
        extend_questions(seeded_examples)
    if len(questions_list) < target_count:
        extend_questions(C.get_question_template_samples(target_count * 2))
    if len(questions_list) < target_count:
        extend_questions(build_role_fallback_questions(role, target_count))

    questions_list = [q for q in questions_list if q.strip()][:target_count]

    if len(questions_list) < target_count:
        logger.error(f"[GENERATE] Unable to assemble assessment questions for role: {role}")
        return json_fail(
            "Could not generate assessment questions. Please try again in a moment.",
            status=500,
        )

    # Create assessment with qa_snapshot
    assessment = TechnicalAssessment.objects.create(
        conversation=conversation,
        interview_form=interview_form,
        qa_snapshot=questions_list,
    )

    # Bulk create questions
    AssessmentQuestion.objects.bulk_create(
        [
            AssessmentQuestion(
                assessment=assessment,
                sequence_number=idx,
                question_payload=AssessmentQuestion.build_payload(text),
            )
            for idx, text in enumerate(questions_list, start=1)
        ]
    )
    logger.info(
        "[GENERATE] Assessment %s created with %d role-based questions for role '%s'",
        assessment.id,
        len(questions_list),
        role,
    )

    # Generate secure URL
    encrypted_token = token_manager.encrypt(assessment.id)
    assessment_url = request.build_absolute_uri(f"/assessment/{encrypted_token}/")

    return json_ok(
        {
            "assessment_id": str(assessment.id),
            "assessment_url": assessment_url,
            "token": encrypted_token,
            "question_count": len(questions_list),
            "redirect": True,
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
@handle_view_errors("Save failed")
def save_assessment(request, assessment_id: str):
    """Save assessment conversation transcript."""
    assessment = get_object_or_fail(TechnicalAssessment, id=assessment_id)
    body = safe_json_parse(request.body)
    messages = validate_field(body, "messages", list)
    session_id = body.get("session_id")

    assessment.transcript = messages
    assessment.save(update_fields=["transcript", "updated_at"])

    logger.info(
        "[ASSESSMENT:SAVE] assessment=%s session=%s messages=%d",
        assessment_id,
        session_id or "-",
        len(messages),
    )

    return json_ok(
        {"assessment_id": str(assessment.id), "message_count": len(messages)}
    )


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
@transaction.atomic
def analyze_assessment(request, assessment_id: str):
    """Analyze assessment responses and save answers."""
    assessment = get_object_or_fail(
        TechnicalAssessment.objects.prefetch_related("questions"), id=assessment_id
    )
    body = safe_json_parse(request.body)

    logger.info("[ASSESSMENT:ANALYZE] assessment=%s questions=%d", assessment_id, assessment.questions.count())

    qa_mapping = body.get("qa_mapping")

    if qa_mapping and isinstance(qa_mapping, dict):
        logger.info(
            "[ASSESSMENT:ANALYZE] Using direct Q&A mapping (%d entries)",
            len(qa_mapping),
        )
        answers_dict = qa_mapping
    else:
        transcript_len = len(assessment.transcript or [])
        logger.info(
            "[ASSESSMENT:ANALYZE] Extracting answers from transcript (%d messages)",
            transcript_len,
        )
        extractor = AssessmentExtractor()
        questions_text = [q.question_text for q in assessment.questions.all()]
        answers_dict = extractor.extract_answers(assessment.transcript, questions_text)

    # Save answers
    saved_answers = {}
    for question in assessment.questions.all():
        answer_key = f"q{question.sequence_number}"
        answer_text = answers_dict.get(answer_key, "")

        CandidateAnswer.create_or_update(question, answer_text)
        saved_answers[answer_key] = answer_text if answer_text else "NIL"

        logger.info(f"[ANALYZE] Saved answer for Q{question.sequence_number}")

    # Mark assessment as completed
    assessment.is_completed = True
    assessment.save(update_fields=["is_completed", "updated_at"])

    logger.info("[ANALYZE] Completed assessment %s", assessment_id)

    return json_ok(
        {
            "assessment_id": str(assessment_id),
            "answers": saved_answers,
            "completed": True,
            "total_questions": assessment.total_questions,
            "answered_questions": assessment.answered_count,
        }
    )


# ============================================================================
# Response Management
# ============================================================================


@csrf_exempt
@require_http_methods(["GET"])
@handle_view_errors("Failed to load response")
def view_response(request, conv_id: int):
    """View full response details for a conversation."""
    conversation = get_object_or_fail(
        VoiceConversation.objects.select_related("interview_form").prefetch_related(
            "assessments", "assessments__questions", "assessments__questions__answer"
        ),
        id=conv_id,
    )

    response_number = VoiceConversation.objects.filter(
        created_at__lte=conversation.created_at
    ).count()

    assessments_data = []
    for assessment in conversation.assessments.all():
        qa_pairs = []
        for question in assessment.questions.all():
            answer_text = "NIL"
            answered_at = None

            try:
                if hasattr(question, "answer") and question.answer:
                    answer_text = question.answer.response_text or "NIL"
                    answered_at = (
                        question.answer.created_at.isoformat()
                        if question.answer.created_at
                        else None
                    )
            except CandidateAnswer.DoesNotExist:
                pass

            qa_pairs.append(
                {
                    "number": question.sequence_number,
                    "question": question.question_text,
                    "answer": answer_text,
                    "answered_at": answered_at,
                }
            )

        assessments_data.append(
            {
                "id": str(assessment.id),
                "completed": assessment.is_completed,
                "qa_pairs": qa_pairs,
                "completion_percentage": assessment.completion_percentage,
            }
        )

    return json_ok(
        {
            "response_number": response_number,
            "created_at": conversation.created_at.strftime("%B %d, %Y - %H:%M"),
            "updated_at": conversation.updated_at.strftime("%B %d, %Y - %H:%M"),
            "user_response": conversation.extracted_info,  # Keep key name for frontend compatibility
            "field_labels": get_field_label_map(conversation.interview_form),
            "messages": conversation.messages,
            "assessments": assessments_data,
            "interview_form": (
                {
                    "id": str(conversation.interview_form.id),
                    "title": conversation.interview_form.title,
                    "role": conversation.interview_form.role,
                }
                if conversation.interview_form
                else None
            ),
        }
    )


@csrf_exempt
@require_POST
@handle_view_errors("Failed to update response")
def edit_response(request, conv_id: int):
    """Edit conversation user response data."""
    conversation = get_object_or_fail(VoiceConversation, id=conv_id)
    body = safe_json_parse(request.body)
    user_response = validate_field(body, "user_response", dict)

    conversation.extracted_info = user_response
    conversation.save(update_fields=["extracted_info", "updated_at"])

    logger.info("[RESPONSES] Updated conversation %s", conv_id)

    return json_ok(
        {
            "conversation_id": conversation.pk,
            "user_response": conversation.extracted_info,
            "updated_at": conversation.updated_at.isoformat(),
        }
    )


@csrf_exempt
@require_http_methods(["DELETE"])
@handle_view_errors("Failed to delete response")
@transaction.atomic
def delete_response(request, conv_id: int):
    """Delete conversation and all associated data."""
    conversation = get_object_or_fail(VoiceConversation, id=conv_id)
    conversation.delete()

    logger.info("[RESPONSES] Deleted conversation %s", conv_id)

    return json_ok({"message": "Response deleted successfully"})
