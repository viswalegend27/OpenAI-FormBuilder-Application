import logging
from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from . import constants as C
from .helper.views_helper import json_fail, json_ok
from .models import Assessment, Conversation, Question, Answer
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
# Security: Token Management
# ============================================================================

class AssessmentTokenManager:
    """Handles encryption and decryption of assessment IDs for secure URLs."""
    
    def __init__(self):
        self.signer = TimestampSigner()
    
    def encrypt(self, assessment_id):
        """Encrypt assessment ID into a URL-safe token."""
        return self.signer.sign(str(assessment_id))
    
    def decrypt(self, token, max_age=ASSESSMENT_TOKEN_MAX_AGE):
        """Decrypt assessment token to retrieve the original ID."""
        try:
            assessment_id = self.signer.unsign(token, max_age=max_age)
            return assessment_id
        except (BadSignature, SignatureExpired) as e:
            logger.warning(f"Invalid assessment token: {e}")
            return None


token_manager = AssessmentTokenManager()


# ============================================================================
# Helper Functions
# ============================================================================

def get_session_payload(request):
    """Build session payload based on request type and assessment mode."""
    payload = C.get_session_payload()
    
    if request.method == "POST":
        body = safe_json_parse(request.body)
        
        if body.get("assessment_mode"):
            qualification = body.get("qualification", "")
            experience = body.get("experience", "")
            payload["instructions"] = C.get_assessment_persona(qualification, experience)
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
    
    return payload


# ============================================================================
# Page Views
# ============================================================================

def voice_page(request):
    """Render the main voice assistant interface."""
    return render(request, "form_ai/voice.html")


def view_responses(request):
    """Display all conversation responses in a list view."""
    conversations = Conversation.objects.filter(
        user_response__isnull=False
    ).exclude(
        user_response={}
    ).select_related().prefetch_related('assessments')
    
    return render(request, "form_ai/responses.html", {
        "conversations": conversations
    })


def conduct_assessment(request, token):
    """Render assessment page using encrypted token for security."""
    assessment_id = token_manager.decrypt(token)
    
    if not assessment_id:
        return render(request, "form_ai/error.html", {
            "error": "Invalid or expired assessment link",
            "message": "This assessment link is no longer valid. Please contact support."
        }, status=400)
    
    assessment = get_object_or_fail(
        Assessment.objects.select_related('conversation').prefetch_related('questions__answer'),
        id=assessment_id
    )
    
    # Build questions list from JSONB data
    questions_list = []
    for question in assessment.questions.all():
        questions_list.append({
            'number': question.question_number,
            'text': question.question_text,
        })
    
    context = {
        'assessment': assessment,
        'assessment_id': str(assessment.id),
        'user_info': assessment.conversation.user_response or {},
        'questions': questions_list,
    }
    
    return render(request, "form_ai/assessment.html", context)


# ============================================================================
# Realtime Session Management
# ============================================================================

@csrf_exempt
@require_http_methods(["GET", "POST"])
@handle_view_errors("Failed to create session")
def create_realtime_session(request):
    """Create OpenAI realtime session with optional assessment mode."""
    client = OpenAIClient()
    payload = get_session_payload(request)
    session_data = client.create_realtime_session(payload)
    
    return json_ok(session_data)


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
    
    conversation = Conversation.objects.create(
        session_id=session_id,
        messages=messages
    )
    
    logger.info(f"✓ Saved conversation {conversation.pk} with {len(messages)} messages")
    
    return json_ok({
        "conversation_id": conversation.pk,
        "created_at": conversation.created_at.isoformat()
    })


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
def analyze_conversation(request):
    """Analyze conversation and extract structured user data using AI."""
    body = safe_json_parse(request.body)
    session_id = validate_field(body, "session_id", str)
    
    conversation = get_object_or_fail(Conversation, session_id=session_id)
    
    client = OpenAIClient()
    extracted_data = client.extract_structured_data(
        conversation.messages,
        DEFAULT_EXTRACTION_KEYS
    )
    
    conversation.user_response = extracted_data
    conversation.save(update_fields=["user_response", "updated_at"])
    
    logger.info(f"✓ Analyzed conversation {conversation.pk}: {extracted_data}")
    
    return json_ok({
        "session_id": session_id,
        "user_response": extracted_data
    })


# ============================================================================
# Assessment Management
# ============================================================================

@csrf_exempt
@require_POST
@handle_view_errors("Failed to generate assessment")
@transaction.atomic
def generate_assessment(request, conv_id):
    """Generate assessment with questions stored as JSONB in separate table."""
    conversation = get_object_or_fail(Conversation, id=conv_id)
    
    if not conversation.user_response:
        return json_fail("No user response data available", status=400)
    
    questions_list = C.get_questions()
    if not questions_list:
        logger.error("No questions available from constants")
        return json_fail("No questions configured", status=500)
    
    assessment = Assessment.objects.create(conversation=conversation)
    
    for index, question_text in enumerate(questions_list, start=1):
        Question.objects.create(
            assessment=assessment,
            data={
                'question_number': index,
                'question_text': question_text,
            }
        )
    
    encrypted_token = token_manager.encrypt(assessment.id)
    assessment_url = request.build_absolute_uri(f"/assessment/{encrypted_token}/")
    
    logger.info(f"✓ Generated assessment {assessment.id} with {len(questions_list)} questions")
    
    return json_ok({
        "assessment_id": str(assessment.id),
        "assessment_url": assessment_url,
        "token": encrypted_token,
        "question_count": len(questions_list),
        "redirect": True
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
    
    return json_ok({
        "assessment_id": str(assessment.id),
        "message_count": len(messages)
    })


@csrf_exempt
@require_POST
@handle_view_errors("Analysis failed")
@transaction.atomic
def analyze_assessment(request, assessment_id):
    """Analyze assessment responses and save answers as JSONB in separate table."""
    assessment = get_object_or_fail(
        Assessment.objects.prefetch_related('questions'),
        id=assessment_id
    )
    body = safe_json_parse(request.body)
    
    logger.info(f"[ANALYZE] Assessment {assessment_id}")
    
    qa_mapping = body.get('qa_mapping', {})
    
    if qa_mapping and isinstance(qa_mapping, dict):
        logger.info(f"[ANALYZE] Using direct Q&A mapping")
        answers_dict = qa_mapping
    else:
        logger.info(f"[ANALYZE] Extracting from {len(assessment.messages)} messages")
        extractor = AssessmentExtractor()
        questions_list = [q.question_text for q in assessment.questions.all()]
        answers_dict = extractor.extract_answers(assessment.messages, questions_list)
    
    saved_answers = {}
    for question in assessment.questions.all():
        answer_key = f"q{question.question_number}"
        answer_text = answers_dict.get(answer_key, "")
        
        answer_obj, created = Answer.objects.update_or_create(
            question=question,
            defaults={
                'data': {
                    'answer_text': answer_text,
                    'question_number': question.question_number,
                    'timestamp': timezone.now().isoformat(),
                }
            }
        )
        
        saved_answers[answer_key] = answer_text
        action = "Created" if created else "Updated"
        logger.info(f"[ANALYZE] {action} answer for Q{question.question_number}")
    
    assessment.completed = True
    assessment.save(update_fields=["completed", "updated_at"])
    
    logger.info(f"[ANALYZE] ✓ Completed assessment {assessment_id}")
    
    return json_ok({
        "assessment_id": str(assessment_id),
        "answers": saved_answers,
        "completed": True,
        "total_questions": assessment.total_questions,
        "answered_questions": assessment.answered_questions
    })


# ============================================================================
# Response Management Views
# ============================================================================

@csrf_exempt
@require_http_methods(["GET"])
@handle_view_errors("Failed to load response")
def view_response(request, conv_id):
    """View full response details for a conversation."""
    conversation = get_object_or_fail(
        Conversation.objects.prefetch_related('assessments__questions__answer'),
        id=conv_id
    )
    
    response_number = Conversation.objects.filter(
        created_at__lte=conversation.created_at
    ).count()
    
    assessments_data = []
    for assessment in conversation.assessments.all():
        assessment_info = {
            'id': str(assessment.id),
            'completed': assessment.completed,
            'questions': []
        }
        
        for question in assessment.questions.all():
            question_data = {
                'number': question.question_number,
                'text': question.question_text,
                'answer': None
            }
            
            if hasattr(question, 'answer'):
                question_data['answer'] = question.answer.answer_text
            
            assessment_info['questions'].append(question_data)
        
        assessments_data.append(assessment_info)
    
    return json_ok({
        "response_number": response_number,
        "created_at": conversation.created_at.strftime("%B %d, %Y - %H:%M"),
        "updated_at": conversation.updated_at.strftime("%B %d, %Y - %H:%M"),
        "user_response": conversation.user_response or {},
        "messages": conversation.messages or [],
        "assessments": assessments_data
    })


@csrf_exempt
@require_POST
@handle_view_errors("Failed to update response")
def edit_response(request, conv_id):
    """Edit conversation user response data."""
    conversation = get_object_or_fail(Conversation, id=conv_id)
    body = safe_json_parse(request.body)
    user_response = validate_field(body, "user_response", dict)
    
    conversation.user_response = user_response
    conversation.save(update_fields=["user_response", "updated_at"])
    
    logger.info(f"✓ Updated conversation {conv_id} user response")
    
    return json_ok({
        "conversation_id": conversation.pk,
        "user_response": conversation.user_response,
        "updated_at": conversation.updated_at.isoformat()
    })


@csrf_exempt
@require_http_methods(["DELETE"])
@handle_view_errors("Failed to delete response")
@transaction.atomic
def delete_response(request, conv_id):
    """Delete conversation and all associated assessments, questions, and answers."""
    conversation = get_object_or_fail(Conversation, id=conv_id)
    conversation.delete()
    
    logger.info(f"✓ Deleted conversation {conv_id} and all related data")
    
    return json_ok({
        "message": "Response and all related assessments deleted successfully"
    })