# views.py

import logging
from typing import Any, Dict
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
    get_object_or_fail,
    handle_view_errors,
    safe_json_parse,
    validate_field,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_EXTRACTION_KEYS = ["name", "qualification", "experience"]
ASSESSMENT_TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


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
# Helper Functions
# ============================================================================


def build_session_payload(request) -> dict:
    """Build session payload based on request type and assessment mode."""
    payload = C.get_session_payload()
    payload["instructions"] = C.build_default_voice_instructions()
    body = safe_json_parse(request.body) if request.method == "POST" else {}
    logger.info("[SESSION] Incoming session request. Method=%s, assessment=%s, interview_id=%s",
                request.method,
                bool(body.get("assessment_mode")),
                request.GET.get("interview_id") or body.get("interview_id"))

    interview_id = request.GET.get("interview_id") or body.get("interview_id")
    interview = None
    interview_questions: list[str] | None = None

    if interview_id:
        logger.info(f"[SESSION] Requested interview_id={interview_id}")
        interview = (
            InterviewForm.objects.prefetch_related("questions")
            .filter(id=interview_id)
            .first()
        )
        if interview:
            interview_questions = interview.question_texts()
            logger.info(
                f"[SESSION] Using interview {interview.id} with "
                f"{len(interview_questions)} questions"
            )
            payload["instructions"] = C.build_interview_instructions(interview)

            # Allow the assistant to trigger verification once it has structured data
            extraction_keys = DEFAULT_EXTRACTION_KEYS
            payload["tools"] = [C.build_verify_tool(extraction_keys)]
            logger.info(
                "[SESSION] Attached interview instructions and verify tool. interview=%s, questions=%d, tools=%s",
                interview.id,
                len(interview_questions),
                [tool.get("name") for tool in payload.get("tools", [])],
            )

        else:
            logger.warning("Interview %s not found for session payload", interview_id)

    if body.get("assessment_mode"):
        qualification = body.get("qualification", "")
        experience = body.get("experience", "")

        if interview_questions is None:
            questions_from_body = body.get("questions")
            if isinstance(questions_from_body, list):
                interview_questions = [
                    str(item).strip()
                    for item in questions_from_body
                    if str(item).strip()
                ]
                logger.info(
                    "[SESSION] Using question payload from frontend: "
                    f"{len(interview_questions)} items"
                )

        if not interview_questions:
            raise AppError(
                "Assessment questions are missing. Reopen the interview builder and retry.",
                status=400,
            )

        payload["instructions"] = C.get_assessment_persona(
            qualification,
            experience,
            questions=interview_questions,
        )
        logger.info(
            f"[SESSION] Built assessment persona for {qualification}/{experience} "
            f"with {len(interview_questions)} questions"
        )
        payload.pop("tools", None)
        payload.pop("tool_choice", None)

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


def clean_verified_data(data: Dict[str, Any] | None) -> Dict[str, str]:
    """Normalize user-provided verification overrides."""
    if not isinstance(data, dict):
        return {}

    cleaned: Dict[str, str] = {}
    for field in DEFAULT_EXTRACTION_KEYS:
        value = data.get(field)
        if value is None:
            continue

        text = str(value).strip()
        if text:
            cleaned[field] = text
    return cleaned


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

    print(f"[VOICE_PAGE] Loaded interview {interview.id} for realtime session")

    return render(
        request,
        "form_ai/voice.html",
        {
            "interview": interview,
            "interview_id": str(interview.id),
            "questions": questions,
        },
    )


def view_responses(request):
    """Display all conversation responses in a list view."""
    conversations = (
        VoiceConversation.objects.filter(extracted_info__isnull=False)
        .exclude(extracted_info={})
        .select_related("interview_form")
        .prefetch_related(
            "assessments", "assessments__questions", "assessments__questions__answer"
        )
    )

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
                question_text=text,
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
    overrides = clean_verified_data(body.get("verified_data"))

    client = OpenAIClient()
    extracted_data = client.extract_structured_data(
        conversation.messages, DEFAULT_EXTRACTION_KEYS
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
    role = interview_form.role or interview_form.title

    # Fetch role-based assessment questions from database
    questions_list = C.get_assessment_questions_for_role(role)

    if not questions_list:
        logger.error(f"[GENERATE] No assessment questions for role: {role}")
        return json_fail(
            f"No technical questions configured for role '{role}'. Please configure assessment questions first.",
            status=400,
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
                assessment=assessment, sequence_number=idx, question_text=text
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


@require_http_methods(["POST"])
@handle_view_errors("Save failed")
def save_assessment(request, assessment_id: str):
    """Save assessment conversation transcript."""
    assessment = get_object_or_fail(TechnicalAssessment, id=assessment_id)
    body = safe_json_parse(request.body)
    messages = validate_field(body, "messages", list)

    assessment.transcript = messages
    assessment.save(update_fields=["transcript", "updated_at"])

    logger.info(
        "[ASSESSMENT] Saved transcript for %s (%d messages)",
        assessment_id,
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

    logger.info(f"[ANALYZE] Assessment {assessment_id}")

    qa_mapping = body.get("qa_mapping")

    if qa_mapping and isinstance(qa_mapping, dict):
        logger.info("[ANALYZE] Using direct Q&A mapping")
        answers_dict = qa_mapping
    else:
        logger.info(f"[ANALYZE] Extracting from {len(assessment.transcript)} messages")
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
