# views.py

import logging
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
    body = safe_json_parse(request.body) if request.method == "POST" else {}

    interview_id = request.GET.get("interview_id") or body.get("interview_id")
    interview = None
    interview_questions: list[str] | None = None

    if interview_id:
        interview = (
            InterviewForm.objects.prefetch_related("questions")
            .filter(id=interview_id)
            .first()
        )
        if interview:
            interview_questions = interview.question_texts()
            payload["instructions"] = C.build_interview_instructions(interview)

    if body.get("assessment_mode"):
        qualification = body.get("qualification", "")
        experience = body.get("experience", "")

        if interview_questions is None:
            questions_from_body = body.get("questions")
            if isinstance(questions_from_body, list):
                interview_questions = [
                    str(item).strip() for item in questions_from_body if str(item).strip()
                ]

        payload["instructions"] = C.get_assessment_persona(
            qualification,
            experience,
            questions=interview_questions,
        )
        payload.pop("tools", None)
        payload.pop("tool_choice", None)

    return payload


# ============================================================================
# Page Views
# ============================================================================


def interview_builder(request):
    """Render interview creation and listing page."""
    interviews = (
        InterviewForm.objects.prefetch_related("questions").order_by("-updated_at")
    )
    return render(
        request,
        "form_ai/interviews.html",
        {
            "interviews": interviews,
            "existing_count": interviews.count(),
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

    title = validate_field(body, "title", str)
    if not title or not title.strip():
        raise AppError("Interview title is required", status=400)

    questions = validate_field(body, "questions", list)
    cleaned_questions = [
        str(item).strip() for item in questions if isinstance(item, str) and item.strip()
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

    return json_ok(
        {
            "interview_id": str(interview.id),
            "question_count": len(cleaned_questions),
            "redirect_url": redirect_url,
        },
        status=201,
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

    logger.info(f"✓ Saved conversation {conversation.pk} with {len(messages)} messages")

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

    client = OpenAIClient()
    extracted_data = client.extract_structured_data(
        conversation.messages, DEFAULT_EXTRACTION_KEYS
    )

    conversation.extracted_info = extracted_data
    conversation.save(update_fields=["extracted_info", "updated_at"])

    logger.info(f"✓ Analyzed conversation {conversation.pk}: {extracted_data}")
    logger.info(f"✓ Conversation {conversation.pk} now has extracted_info saved")

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
    """Generate assessment with questions."""
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
    questions_list = (
        interview_form.question_texts() if interview_form else C.get_questions()
    )

    if not questions_list:
        return json_fail(
            "No interview questions available. Please configure the interview first.",
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

    # Generate secure URL
    encrypted_token = token_manager.encrypt(assessment.id)
    assessment_url = request.build_absolute_uri(f"/assessment/{encrypted_token}/")

    logger.info(
        f"✓ Generated assessment {assessment.id} with {len(questions_list)} questions"
    )

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
@require_POST
@handle_view_errors("Save failed")
def save_assessment(request, assessment_id: str):
    """Save assessment conversation transcript."""
    assessment = get_object_or_fail(TechnicalAssessment, id=assessment_id)
    body = safe_json_parse(request.body)
    messages = validate_field(body, "messages", list)

    assessment.transcript = messages
    assessment.save(update_fields=["transcript", "updated_at"])

    logger.info(f"✓ Assessment {assessment_id}: Saved {len(messages)} messages")

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

    logger.info(f"[ANALYZE] ✓ Completed assessment {assessment_id}")

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

    logger.info(f"✓ Updated conversation {conv_id}")

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

    logger.info(f"✓ Deleted conversation {conv_id}")

    return json_ok({"message": "Response deleted successfully"})
