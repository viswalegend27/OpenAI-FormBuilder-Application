# views.py
import logging

from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import constants as C
from .helper.views_helper import json_fail, json_ok
from .models import Assessment, Conversation
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
# URL Encryption Utilities
# ============================================================================

signer = TimestampSigner()


def encrypt_assessment_id(assessment_id):
    """Encrypt assessment ID into a URL-safe token."""
    return signer.sign(str(assessment_id))


def decrypt_assessment_token(token, max_age=ASSESSMENT_TOKEN_MAX_AGE):
    """
    Decrypt assessment token to get ID.
    Returns assessment_id or None if invalid/expired.
    """
    try:
        assessment_id = signer.unsign(token, max_age=max_age)
        return assessment_id
    except (BadSignature, SignatureExpired) as e:
        logger.warning(f"Invalid assessment token: {e}")
        return None


# ============================================================================
# Page Views
# ============================================================================

def voice_page(request):
    """Render the voice assistant page."""
    return render(request, "form_ai/voice.html")


def view_responses(request):
    """Display all conversation responses."""
    conversations = Conversation.objects.filter(
        user_response__isnull=False
    ).exclude(user_response={}).order_by('-created_at')

    return render(request, "form_ai/responses.html", {
        "conversations": conversations
    })


def conduct_assessment(request, token):
    """
    Render assessment page using encrypted token.
    Validates token and retrieves assessment.
    """
    assessment_id = decrypt_assessment_token(token)
    
    if not assessment_id:
        return render(request, "form_ai/error.html", {
            "error": "Invalid or expired assessment link",
            "message": "This assessment link is no longer valid. Please contact support."
        }, status=400)
    
    assessment = get_object_or_fail(Assessment, id=assessment_id)
    user_info = assessment.conversation.user_response or {}

    return render(request, "form_ai/assessment.html", {
        "assessment": assessment,
        "assessment_id": str(assessment.id),
        "user_info": user_info
    })


# ============================================================================
# Realtime Session Management
# ============================================================================

@csrf_exempt
@handle_view_errors("Failed to create session")
def create_realtime_session(request):
    """Create OpenAI realtime session with optional assessment mode."""
    if request.method not in ("GET", "POST"):
        return json_fail("Method not allowed", status=405)

    client = OpenAIClient()
    payload = _get_session_payload(request)
    session_data = client.create_realtime_session(payload)

    return json_ok(session_data)


def _get_session_payload(request) -> dict:
    """Get session payload based on request type and mode."""
    payload = C.get_session_payload()

    if request.method == "POST":
        body = safe_json_parse(request.body)
        if body.get("assessment_mode"):
            qual = body.get("qualification", "")
            exp = body.get("experience", "")
            payload["instructions"] = C.get_assessment_persona(qual, exp)
            payload.pop("tools", None)
            payload.pop("tool_choice", None)

    return payload


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

    conv = Conversation.objects.create(
        session_id=session_id,
        messages=messages
    )

    return json_ok({
        "conversation_id": conv.pk,
        "created_at": conv.created_at.isoformat()
    })


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
def analyze_conversation(request):
    """Analyze conversation and extract user responses."""
    body = safe_json_parse(request.body)
    session_id = validate_field(body, "session_id", str)

    conv = get_object_or_fail(Conversation, session_id=session_id)
    client = OpenAIClient()

    extracted = client.extract_structured_data(
        conv.messages,
        DEFAULT_EXTRACTION_KEYS
    )

    conv.user_response = extracted
    conv.save(update_fields=["user_response", "updated_at"])

    return json_ok({
        "session_id": session_id,
        "user_response": extracted
    })


# ============================================================================
# Assessment Management
# ============================================================================

@csrf_exempt
@require_POST
@handle_view_errors("Failed to generate assessment")
def generate_assessment(request, conv_id):
    """
    Generate assessment with encrypted URL.
    Returns encrypted assessment URL for secure access.
    """
    conv = get_object_or_fail(Conversation, id=conv_id)

    if not conv.user_response:
        return json_fail("No user response data", status=400)

    questions = C.get_questions()
    if not questions:
        logger.error("No questions available from constants")
        return json_fail("No questions configured", status=500)

    assessment = Assessment.objects.create(
        conversation=conv,
        questions=questions
    )

    # Generate encrypted token
    encrypted_token = encrypt_assessment_id(assessment.id)
    assessment_url = request.build_absolute_uri(f"/assessment/{encrypted_token}/")

    logger.info(f"✓ Generated encrypted assessment: {assessment.id}")

    return json_ok({
        "assessment_id": str(assessment.id),
        "assessment_url": assessment_url,
        "token": encrypted_token,
        "questions": questions,
        "redirect": True  # Signal frontend to redirect
    })


@csrf_exempt
@require_POST
@handle_view_errors("Save failed")
def save_assessment(request, assessment_id):
    """Save assessment conversation messages."""
    assessment = get_object_or_fail(Assessment, id=assessment_id)
    body = safe_json_parse(request.body)
    messages = validate_field(body, "messages", list)

    assessment.messages = messages
    assessment.save(update_fields=["messages", "updated_at"])

    logger.info(f"✓ Assessment {assessment_id}: Saved {len(messages)} messages")

    return json_ok({"assessment_id": str(assessment.id)})


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
def analyze_assessment(request, assessment_id):
    """Analyze assessment responses and extract answers."""
    assessment = get_object_or_fail(Assessment, id=assessment_id)
    body = safe_json_parse(request.body)

    logger.info(f"[ANALYZE] Assessment {assessment_id}")

    # Get direct Q&A mapping from frontend
    qa_mapping = body.get('qa_mapping', {})

    if qa_mapping and isinstance(qa_mapping, dict) and any(qa_mapping.values()):
        logger.info(f"[ANALYZE] Using direct mapping")
        answers = {
            f"q{i+1}": qa_mapping.get(f"q{i+1}", "")
            for i in range(len(assessment.questions))
        }
    else:
        logger.info(f"[ANALYZE] Extracting from {len(assessment.messages)} messages")
        extractor = AssessmentExtractor()
        answers = extractor.extract_answers(
            assessment.messages,
            assessment.questions
        )

    logger.info(f"[ANALYZE] ✓ Final answers: {answers}")

    assessment.answers = answers
    assessment.completed = True
    assessment.save(update_fields=["answers", "completed", "updated_at"])

    return json_ok({
        "assessment_id": str(assessment.id),
        "answers": answers,
        "completed": True
    })


# ============================================================================
# Response Management Views
# ============================================================================

@csrf_exempt
@handle_view_errors("Failed to load response")
def view_response(request, conv_id):
    """View full response details."""
    conv = get_object_or_fail(Conversation, id=conv_id)
    response_number = Conversation.objects.filter(
        created_at__lte=conv.created_at
    ).count()

    return json_ok({
        "response_number": response_number,
        "created_at": conv.created_at.strftime("%B %d, %Y - %H:%M"),
        "updated_at": conv.updated_at.strftime("%B %d, %Y - %H:%M"),
        "user_response": conv.user_response or {},
        "messages": conv.messages or []
    })


@csrf_exempt
@require_POST
@handle_view_errors("Failed to update response")
def edit_response(request, conv_id):
    """Edit conversation user response data."""
    conv = get_object_or_fail(Conversation, id=conv_id)
    body = safe_json_parse(request.body)
    user_response = validate_field(body, "user_response", dict)

    conv.user_response = user_response
    conv.save(update_fields=["user_response", "updated_at"])

    return json_ok({
        "conversation_id": conv.pk,
        "user_response": conv.user_response,
        "updated_at": conv.updated_at.isoformat()
    })


@csrf_exempt
@handle_view_errors("Failed to delete response")
def delete_response(request, conv_id):
    """Delete conversation and associated assessments."""
    if request.method != "DELETE":
        return json_fail("Method not allowed", status=405)

    conv = get_object_or_fail(Conversation, id=conv_id)
    Assessment.objects.filter(conversation=conv).delete()
    conv.delete()

    return json_ok({"message": "Response deleted successfully"})