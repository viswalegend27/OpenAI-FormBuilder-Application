import json
import logging
import os
from typing import Any, Dict, List

from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import constants as C
from .helper.views_helper import (
    AppError,
    json_fail,
    json_ok,
    post_json,
    require_env,
)
from .models import Assessment, Conversation
from .views_schema_ import build_dynamic_schema, build_extractor_messages

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

DEFAULT_EXTRACTION_KEYS = ["name", "qualification", "experience"]
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_REALTIME_URL = "https://api.openai.com/v1/realtime/sessions"


# ============================================================================
# Utility Functions
# ============================================================================

def get_openai_headers(api_key: str) -> Dict[str, str]:
    """Generate OpenAI API headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def parse_json_from_response(content: str) -> Any:
    """Extract and parse JSON from response, handling markdown code blocks."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return json.loads(content)


def safe_json_parse(body: bytes) -> Dict[str, Any]:
    """Safely parse JSON from request body."""
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to parse request body: {e}")
        return {}


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


def conduct_assessment(request, assessment_id):
    """Render assessment page."""
    assessment = get_object_or_404(Assessment, id=assessment_id)
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
def create_realtime_session(request):
    """Create OpenAI realtime session with optional assessment mode."""
    try:
        if request.method not in ("GET", "POST"):
            return json_fail("Method not allowed", status=405)

        api_key = require_env("OPENAI_API_KEY")
        headers = get_openai_headers(api_key)
        payload = _get_session_payload(request)

        data = post_json(OPENAI_REALTIME_URL, headers, payload, timeout=20)

        if not data.get("client_secret", {}).get("value"):
            logger.warning("Session created but client_secret.value is missing")

        return json_ok({
            "id": data.get("id"),
            "model": data.get("model"),
            "client_secret": data.get("client_secret"),
        })
    except AppError as e:
        return json_fail(e.message, status=e.status, details=e.details)


def _get_session_payload(request) -> Dict[str, Any]:
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
def save_conversation(request):
    """Save conversation messages to database."""
    try:
        body = safe_json_parse(request.body)
        messages = body.get("messages")

        if not isinstance(messages, list):
            return json_fail("Missing or invalid 'messages'", status=400)

        session_id = body.get("session_id")
        conv = Conversation.objects.create(
            session_id=session_id,
            messages=messages
        )

        return json_ok({
            "conversation_id": conv.pk,
            "created_at": conv.created_at.isoformat()
        })
    except Exception as exc:
        logger.exception("Failed saving conversation")
        return json_fail("Internal error", status=500, details=str(exc))


@csrf_exempt
@require_POST
def analyze_conversation(request):
    """Analyze conversation and extract user responses."""
    try:
        body = safe_json_parse(request.body)
        session_id = body.get("session_id")

        if not session_id:
            return json_fail("session_id is required", status=400)

        conv = get_object_or_404(Conversation, session_id=session_id)
        api_key = require_env("OPENAI_API_KEY")

        extracted = _analyze_user_responses(
            conv.messages,
            api_key,
            DEFAULT_EXTRACTION_KEYS
        )

        conv.user_response = extracted
        conv.save(update_fields=["user_response", "updated_at"])

        return json_ok({
            "session_id": session_id,
            "user_response": extracted
        })
    except Exception as exc:
        logger.exception("Failed analyzing conversation")
        return json_fail("Analysis failed", status=500, details=str(exc))


def _analyze_user_responses(
    messages: List[Dict[str, Any]],
    api_key: str,
    keys: List[str]
) -> Dict[str, Any]:
    """Analyze conversation messages and extract structured data."""
    headers = get_openai_headers(api_key)
    json_schema = build_dynamic_schema(keys)

    payload = {
        "model": os.getenv("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": json_schema
        },
        "messages": build_extractor_messages(messages, keys),
    }

    data = post_json(OPENAI_CHAT_URL, headers, payload, timeout=30)

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {k: parsed.get(k, "") for k in keys}
    except (KeyError, json.JSONDecodeError, IndexError) as e:
        logger.warning(f"Failed to parse analysis response: {e}")
        return {k: "" for k in keys}


# ============================================================================
# Assessment Management
# ============================================================================

@csrf_exempt
@require_POST
def generate_assessment(request, conv_id):
    """Generate assessment with expertise-based questions."""
    try:
        conv = get_object_or_404(Conversation, id=conv_id)

        if not conv.user_response:
            return json_fail("No user response data", status=400)

        qualification = conv.user_response.get("qualification", "")
        experience = conv.user_response.get("experience", "")

        api_key = require_env("OPENAI_API_KEY")
        questions = _generate_expertise_questions(qualification, experience, api_key)

        assessment = Assessment.objects.create(
            conversation=conv,
            questions=questions
        )

        assessment_url = request.build_absolute_uri(f"/assessment/{assessment.id}/")

        return json_ok({
            "assessment_id": str(assessment.id),
            "assessment_url": assessment_url,
            "questions": questions
        })
    except Exception as exc:
        logger.exception("Failed generating assessment")
        return json_fail("Failed to generate assessment", status=500, details=str(exc))


@csrf_exempt
@require_POST
def save_assessment(request, assessment_id):
    """Save assessment conversation messages."""
    try:
        assessment = get_object_or_404(Assessment, id=assessment_id)
        body = safe_json_parse(request.body)

        messages = body.get("messages")
        if not isinstance(messages, list):
            return json_fail("Invalid messages", status=400)

        logger.info(f"✓ Assessment {assessment_id}: Saved {len(messages)} messages")
        
        assessment.messages = messages
        assessment.save(update_fields=["messages", "updated_at"])

        return json_ok({"assessment_id": str(assessment.id)})
    except Exception as exc:
        logger.exception("Failed saving assessment")
        return json_fail("Save failed", status=500, details=str(exc))


@csrf_exempt
@require_POST
def analyze_assessment(request, assessment_id):
    """Analyze assessment responses and extract answers."""
    try:
        assessment = get_object_or_404(Assessment, id=assessment_id)
        body = safe_json_parse(request.body)
        
        logger.info(f"[ANALYZE] Assessment {assessment_id}")
        
        # Get direct Q&A mapping from frontend
        qa_mapping = body.get('qa_mapping', {})
        
        if qa_mapping and isinstance(qa_mapping, dict) and any(qa_mapping.values()):
            logger.info(f"[ANALYZE] Using direct mapping: {qa_mapping}")
            answers = {
                f"q{i+1}": qa_mapping.get(f"q{i+1}", "")
                for i in range(len(assessment.questions))
            }
        else:
            logger.info(f"[ANALYZE] Extracting from {len(assessment.messages)} messages")
            api_key = require_env("OPENAI_API_KEY")
            answers = _extract_assessment_answers(
                assessment.messages,
                assessment.questions,
                api_key
            )
        
        logger.info(f"[ANALYZE] ✓ Final answers: {answers}")
        
        assessment.answers = answers
        assessment.completed = True
        assessment.save(update_fields=["answers", "completed", "updated_at"])

        return json_ok({
            "assessment_id": str(assessment.id),
            "answers": answers
        })
    except Exception as exc:
        logger.exception("Failed analyzing assessment")
        return json_fail("Analysis failed", status=500, details=str(exc))


# ============================================================================
# Assessment Helper Functions
# ============================================================================

def _generate_expertise_questions(
    qualification: str,
    experience: str,
    api_key: str
) -> List[Dict[str, str]]:
    """Generate technical questions based on qualification and experience."""
    headers = get_openai_headers(api_key)

    prompt = (
        f"Generate exactly 3 technical interview questions for a candidate with:\n"
        f"- Qualification: {qualification}\n"
        f"- Experience: {experience}\n\n"
        f"Questions should be:\n"
        f"1. One fundamental concept question\n"
        f"2. One practical/scenario-based question\n"
        f"3. One advanced/problem-solving question\n\n"
        f'Return as JSON array: [{{"q": "question text"}}]'
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }

    try:
        data = post_json(OPENAI_CHAT_URL, headers, payload, timeout=20)
        content = data["choices"][0]["message"]["content"]
        questions = parse_json_from_response(content)
        return questions[:3]
    except Exception as e:
        logger.warning(f"Question generation failed: {e}")
        return [
            {"q": "Explain a fundamental concept in your field"},
            {"q": "Describe a practical project you've worked on"},
            {"q": "How would you solve a complex technical challenge?"}
        ]


def _extract_assessment_answers(
    messages: List[Dict],
    questions: List[Dict],
    api_key: str
) -> Dict[str, str]:
    """
    Extract answers from messages using AI.
    Called only when frontend doesn't send direct mapping.
    """
    logger.info("[EXTRACT] Starting AI extraction")
    
    headers = get_openai_headers(api_key)
    
    # Sort messages by timestamp
    sorted_messages = sorted(messages, key=lambda m: m.get('ts', ''))
    
    # Build conversation
    conversation_text = "\n".join([
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
        for m in sorted_messages
    ])
    
    # Build questions
    questions_text = "\n".join([
        f"Q{i+1}: {q['q']}" for i, q in enumerate(questions)
    ])
    
    prompt = f"""Extract the candidate's answers from this interview.

QUESTIONS:
{questions_text}

CONVERSATION:
{conversation_text}

INSTRUCTIONS:
- Extract only USER's substantive answers
- Match answers to questions in order
- Ignore trailing "I don't know" or incomplete responses
- Return empty string if not answered

Return JSON: {{"q1": "answer", "q2": "answer", "q3": "answer"}}"""

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    try:
        data = post_json(OPENAI_CHAT_URL, headers, payload, timeout=30)
        content = data["choices"][0]["message"]["content"]
        result = parse_json_from_response(content)
        logger.info(f"[EXTRACT] ✓ Extracted: {result}")
        return result
    except Exception as e:
        logger.error(f"[EXTRACT] ✗ Failed: {e}")
        return {"q1": "", "q2": "", "q3": ""}


# ============================================================================
# Assessment Helper Functions
# ============================================================================

def _generate_expertise_questions(
    qualification: str,
    experience: str,
    api_key: str
) -> List[Dict[str, str]]:
    """Generate technical questions based on qualification and experience."""
    headers = get_openai_headers(api_key)

    prompt = (
        f"Generate exactly 3 technical interview questions for a candidate "
        f"with:\n- Qualification: {qualification}\n- Experience: {experience}"
        f"\n\nQuestions should be:\n1. One fundamental concept question\n"
        f"2. One practical/scenario-based question\n"
        f"3. One advanced/problem-solving question\n\n"
        f'Return as JSON array: [{{"q": "question text"}}]'
    )

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }

    try:
        data = post_json(OPENAI_CHAT_URL, headers, payload, timeout=20)
        content = data["choices"][0]["message"]["content"]
        questions = parse_json_from_response(content)
        return questions[:3]
    except (KeyError, json.JSONDecodeError, IndexError, AppError) as e:
        logger.warning(f"Failed to generate questions: {e}")
        return _get_fallback_questions()


def _extract_assessment_answers(
    messages: List[Dict],
    questions: List[Dict],
    api_key: str
) -> Dict[str, str]:
    """
    Extract user answers from assessment conversation.
    Uses pattern matching first, then AI extraction as fallback.
    """
    logger.info(f"[EXTRACT] Starting extraction for {len(questions)} questions")
    logger.info(f"[EXTRACT] Messages count: {len(messages)}")
    
    # Sort messages by timestamp
    sorted_messages = sorted(messages, key=lambda m: m.get('ts', ''))
    
    logger.info(f"[EXTRACT] Sorted messages:")
    for i, msg in enumerate(sorted_messages):
        logger.info(f"  [{i}] {msg.get('role')}: {msg.get('content', '')[:100]}")
    
    # Try pattern matching first
    answers = {}
    
    for q_idx, question in enumerate(questions):
        q_key = f"q{q_idx + 1}"
        q_text = question.get('q', '').lower()
        
        logger.info(f"[EXTRACT] Looking for Q{q_idx + 1}: {q_text[:50]}...")
        
        # Find question in messages
        for i, msg in enumerate(sorted_messages):
            if msg.get('role') == 'assistant':
                content_lower = msg.get('content', '').lower()
                
                # Check if this message contains the question
                # Match key words from question
                key_words = [w for w in q_text.split() if len(w) > 4]
                matches = sum(1 for word in key_words if word in content_lower)
                
                if matches >= min(3, len(key_words)):
                    logger.info(f"[EXTRACT] Found question at index {i}")
                    
                    # Get next user message
                    for j in range(i + 1, len(sorted_messages)):
                        if sorted_messages[j].get('role') == 'user':
                            answer = sorted_messages[j].get('content', '').strip()
                            answers[q_key] = answer
                            logger.info(f"[EXTRACT] Found answer: {answer[:100]}")
                            break
                    break
    
    # If pattern matching found answers, return them
    if any(answers.values()):
        logger.info(f"[EXTRACT] Pattern matching successful: {answers}")
        return {f"q{i+1}": answers.get(f"q{i+1}", "") for i in range(len(questions))}
    
    # Fallback to AI extraction
    logger.info("[EXTRACT] Pattern matching failed, using AI extraction")
    return _ai_extract_answers(sorted_messages, questions, api_key)


def _ai_extract_answers(
    messages: List[Dict],
    questions: List[Dict],
    api_key: str
) -> Dict[str, str]:
    """Use AI to extract answers when pattern matching fails."""
    logger.info("[AI_EXTRACT] Starting AI extraction")
    
    headers = get_openai_headers(api_key)
    
    # Build conversation text
    conversation_lines = []
    for msg in messages:
        role = msg.get('role', 'unknown').upper()
        content = msg.get('content', '')
        conversation_lines.append(f"{role}: {content}")
    
    conversation_text = "\n".join(conversation_lines)
    
    # Build questions text
    questions_text = "\n".join([
        f"Question {i+1}: {q['q']}" for i, q in enumerate(questions)
    ])
    
    prompt = f"""Extract the candidate's answers from this technical interview.

QUESTIONS ASKED:
{questions_text}

CONVERSATION:
{conversation_text}

INSTRUCTIONS:
- Extract only the USER's substantive answers to each question
- Match answers in chronological order
- Ignore phrases like "I don't know" that appear after real answers
- If a question wasn't answered substantively, use empty string

Return JSON object with keys q1, q2, q3:
{{"q1": "answer text", "q2": "answer text", "q3": "answer text"}}"""

    logger.info(f"[AI_EXTRACT] Prompt:\n{prompt[:500]}...")
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    try:
        data = post_json(OPENAI_CHAT_URL, headers, payload, timeout=30)
        content = data["choices"][0]["message"]["content"]
        
        logger.info(f"[AI_EXTRACT] Raw response: {content}")
        
        result = parse_json_from_response(content)
        logger.info(f"[AI_EXTRACT] Parsed result: {result}")
        
        return result
    except (KeyError, json.JSONDecodeError, IndexError, AppError) as e:
        logger.error(f"[AI_EXTRACT] Failed: {e}")
        return {"q1": "", "q2": "", "q3": ""}


def _get_fallback_questions() -> List[Dict[str, str]]:
    """Return fallback questions when generation fails."""
    return [
        {"q": "Explain a fundamental concept in your field"},
        {"q": "Describe a practical project you've worked on"},
        {"q": "How would you solve a complex technical challenge?"}
    ]


@csrf_exempt
def view_response(request, conv_id):
    """View full response details."""
    try:
        conv = get_object_or_404(Conversation, id=conv_id)
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
    except Exception as exc:
        logger.exception("Failed to view response")
        return json_fail("Failed to load response", status=500, details=str(exc))


@csrf_exempt
@require_POST
def edit_response(request, conv_id):
    """Edit conversation user response data."""
    try:
        conv = get_object_or_404(Conversation, id=conv_id)
        body = safe_json_parse(request.body)

        user_response = body.get("user_response", {})
        if not isinstance(user_response, dict):
            return json_fail("Invalid user_response data", status=400)

        conv.user_response = user_response
        conv.save(update_fields=["user_response", "updated_at"])

        return json_ok({
            "conversation_id": conv.pk,
            "user_response": conv.user_response,
            "updated_at": conv.updated_at.isoformat()
        })
    except Exception as exc:
        logger.exception("Failed to edit response")
        return json_fail("Failed to update response", status=500, details=str(exc))


@csrf_exempt
def delete_response(request, conv_id):
    """Delete conversation and associated assessments."""
    if request.method != "DELETE":
        return json_fail("Method not allowed", status=405)

    try:
        conv = get_object_or_404(Conversation, id=conv_id)
        Assessment.objects.filter(conversation=conv).delete()
        conv.delete()

        return json_ok({"message": "Response deleted successfully"})
    except Exception as exc:
        logger.exception("Failed to delete response")
        return json_fail("Failed to delete response", status=500, details=str(exc))