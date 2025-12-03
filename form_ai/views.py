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
from .helper.views_helper import AppError, json_ok
from .models import (
    VoiceConversation,
    TechnicalAssessment,
    InterviewForm,
)
from .workflow import AssessmentFlow, ConversationFlow, InterviewFlow
from .views_schema_ import (
    OpenAIClient,
    QuestionIntentSummarizer,
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
    interview: InterviewForm, questions: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    """Use the LLM-driven summarizer with lightweight caching."""
    cache_key = str(interview.id)
    freshness_token = f"{interview.updated_at.timestamp()}:{len(questions)}"

    cached = QUESTION_INTENT_CACHE.get(cache_key)
    if cached and cached.get("token") == freshness_token:
        return cached["data"]

    summarizer = QuestionIntentSummarizer()
    payload = []
    for question in questions:
        text = (question.get("text") or "").strip()
        if not text:
            continue
        payload.append(
            {
                "id": str(question.get("id")),
                "question": text,
                "sequence": question.get("sequence_number"),
            }
        )

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
    question: dict[str, Any], metadata: dict[str, Any], used_keys: set[str]
) -> dict[str, Any]:
    """Create a verification field descriptor for a specific interview question."""
    question_text = (question.get("text") or "").strip()
    label = normalize_field_label(question_text, metadata.get("label"))
    description = metadata.get("summary") or question_text
    raw_key = metadata.get("key") or label
    fallback_key = f"question_{question.get('sequence_number')}"
    slug = slugify_field_key(raw_key, fallback=fallback_key)
    key = ensure_unique_key(slug, used_keys)
    return {
        "key": key,
        "label": label,
        "placeholder": "Confirm the candidate's answer",
        "description": description,
        "sequence_number": question.get("sequence_number"),
        "question_id": str(question.get("id")),
        "helper_text": question_text,
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
        metadata = question_summaries.get(str(question.get("id")), {})
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
    verification_fields: list[dict[str, Any]] = []
    extraction_keys: list[str] = []

    if interview_id:
        logger.info(f"[SESSION] Requested interview_id={interview_id}")
        interview = get_object_or_fail(InterviewForm, id=interview_id)
        verification_fields, extraction_keys = get_verification_schema(interview)
    elif not assessment_mode:
        raise AppError(
            "Interview ID is required to start a realtime session.",
            status=400,
        )

    if assessment_mode:
        qualification = body.get("qualification", "")
        experience = body.get("experience", "")

        if frontend_questions:
            logger.info(
                "[SESSION][ASSESSMENT] Using %d question(s) from frontend payload",
                len(frontend_questions),
            )

        questions_for_persona = frontend_questions or []
        if not questions_for_persona and interview:
            questions_for_persona = interview.question_texts()

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
        payload["instructions"] = C.build_interview_instructions(interview)
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


# ============================================================================
# Page Views
# ============================================================================


def interview_builder(request):
    """Render interview creation and listing page."""
    interviews = list(InterviewForm.objects.order_by("-updated_at"))
    if not interviews:
        InterviewFlow.ensure_seed_interview()
        interviews = list(InterviewForm.objects.order_by("-updated_at"))

    for interview in interviews:
        entries = interview.get_question_entries()
        interview.question_rows = entries
        interview.question_sections = InterviewFlow.to_section_groups(entries)
    print(f"[INTERVIEW_BUILDER] Loaded {len(interviews)} interviews")

    return render(
        request,
        "form_ai/interviews.html",
        {
            "interviews": interviews,
            "existing_count": len(interviews),
            "required_section": InterviewFlow.required_section_template(),
        },
    )


def voice_page(request, interview_id: str | None = None):
    """Render the main voice assistant interface."""
    if not interview_id:
        return redirect("interview_builder")

    interview = get_object_or_fail(InterviewForm, id=interview_id)

    questions = [
        {"number": entry["sequence_number"], "text": entry["text"]}
        for entry in interview.ordered_questions()
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
    )

    conversations = list(conversations_queryset)
    for conversation in conversations:
        conversation.display_fields = build_display_fields(conversation)

    interview_map: Dict[str | None, list[VoiceConversation]] = {}
    for conversation in conversations:
        key = str(conversation.interview_form.id) if conversation.interview_form else None
        interview_map.setdefault(key, []).append(conversation)

    interviews = list(InterviewForm.objects.order_by("-updated_at"))
    interview_groups: list[dict[str, Any]] = []
    for interview in interviews:
        interview_groups.append(
            {
                "interview": interview,
                "responses": interview_map.get(str(interview.id), []),
                "voice_url": request.build_absolute_uri(
                    reverse("voice_page", args=[interview.id])
                ),
            }
        )

    unassigned_responses = interview_map.get(None, [])
    latest_response = conversations[0].created_at if conversations else None

    return render(
        request,
        "form_ai/responses.html",
        {
            "interview_groups": interview_groups,
            "unassigned_responses": unassigned_responses,
            "interview_count": len(interviews),
            "response_count": len(conversations),
            "latest_response": latest_response,
        },
    )


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
            "conversation",
            "interview_form",
            "conversation__interview_form",
            "answer_sheet",
        ),
        id=assessment_id,
    )

    questions_list = [
        {"number": entry["sequence_number"], "text": entry["text"]}
        for entry in assessment.get_question_entries()
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

    sections = validate_field(body, "sections", list)
    interview = InterviewFlow.create_form(
        title=title,
        summary=body.get("summary") or "",
        ai_prompt=body.get("ai_prompt") or "",
        sections=sections,
    )

    redirect_path = reverse("voice_page", args=[interview.id])
    redirect_url = request.build_absolute_uri(redirect_path)
    print(
        f"[CREATE_INTERVIEW] Created interview {interview.id} "
        f"({len(interview.get_question_entries())} questions)"
    )

    return json_ok(
        {
            "interview_id": str(interview.id),
            "question_count": len(interview.get_question_entries()),
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
    interview = get_object_or_fail(InterviewForm, id=interview_id)

    payload = InterviewFlow.delete_form(interview)
    return json_ok(payload)


@csrf_exempt
@require_http_methods(["DELETE"])
@handle_view_errors("Failed to delete interview question")
@transaction.atomic
def delete_interview_question(request, interview_id: str, question_id: str):
    """Delete a single interview question and resequence the remainder."""
    form = get_object_or_fail(InterviewForm, id=interview_id)

    remaining = InterviewFlow.remove_question(form, question_id)
    return json_ok(
        {
            "interview_id": str(form.id),
            "question_id": question_id,
            "remaining_questions": remaining,
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

    conversation = ConversationFlow.save_conversation(
        messages=messages,
        session_id=session_id,
        interview_form=interview_form,
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

    ConversationFlow.apply_analysis(conversation, extracted_data)

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

    assessment, questions_list = AssessmentFlow.generate_for_conversation(
        conversation, target_count=TARGET_ASSESSMENT_QUESTIONS
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

    message_count = AssessmentFlow.save_transcript(assessment, messages, session_id)

    return json_ok(
        {"assessment_id": str(assessment.id), "message_count": message_count}
    )


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
@transaction.atomic
def analyze_assessment(request, assessment_id: str):
    """Analyze assessment responses and save answers."""
    assessment = get_object_or_fail(
        TechnicalAssessment.objects.select_related("answer_sheet"), id=assessment_id
    )
    body = safe_json_parse(request.body)

    result = AssessmentFlow.analyze_answers(
        assessment,
        qa_mapping=body.get("qa_mapping"),
    )

    return json_ok(
        {
            "assessment_id": str(assessment_id),
            "answers": result["answers"],
            "completed": True,
            "total_questions": result["total_questions"],
            "answered_questions": result["answered_questions"],
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
            "assessments", "assessments__answer_sheet"
        ),
        id=conv_id,
    )

    response_number = VoiceConversation.objects.filter(
        created_at__lte=conversation.created_at
    ).count()

    assessments_data = []
    for assessment in conversation.assessments.all():
        answers = (assessment.answer_sheet.answers if hasattr(assessment, "answer_sheet") else {}) or {}
        qa_pairs = []
        for question in assessment.get_question_entries():
            question_id = question["id"]
            answer_text = answers.get(question_id) or "NIL"
            qa_pairs.append(
                {
                    "number": question["sequence_number"],
                    "question": question["text"],
                    "answer": answer_text,
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


@csrf_exempt
@require_http_methods(["DELETE"])
@handle_view_errors("Failed to delete assessment")
@transaction.atomic
def delete_assessment(request, assessment_id):
    """Delete an assessment and associated answers."""
    assessment = get_object_or_fail(
        TechnicalAssessment.objects.select_related("conversation"), id=assessment_id
    )
    conversation, remaining = AssessmentFlow.delete_assessment(assessment)

    return json_ok(
        {
            "assessment_id": str(assessment_id),
            "conversation_id": conversation.id,
            "remaining_assessments": remaining,
        }
    )
