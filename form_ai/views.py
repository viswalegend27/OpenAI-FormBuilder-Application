import logging
import json
import os
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .helper.views_helper import AppError, json_ok, json_fail, require_env, post_json
from . import constants as C
from .models import Conversation, Assessment
from .views_schema_ import extract_keys_from_markdown, build_dynamic_schema, build_extractor_messages
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def voice_page(request):
    return render(request, "form_ai/voice.html")


@csrf_exempt
def create_realtime_session(request):
    try:
        if request.method not in ("GET", "POST"):
            return json_fail("Method not allowed", status=405)

        api_key = require_env("OPENAI_API_KEY")
        url = "https://api.openai.com/v1/realtime/sessions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Check if this is an assessment session
        if request.method == "POST":
            try:
                body = json.loads(request.body.decode("utf-8") or "{}")
                if body.get("assessment_mode"):
                    # Use assessment persona
                    qual = body.get("qualification", "")
                    exp = body.get("experience", "")
                    payload = C.get_session_payload()
                    payload["instructions"] = C.get_assessment_persona(qual, exp)
                    payload.pop("tools", None)  # No tools for assessment
                    payload.pop("tool_choice", None)
                else:
                    payload = C.get_session_payload()
            except:
                payload = C.get_session_payload()
        else:
            payload = C.get_session_payload()

        data = post_json(url, headers, payload, timeout=20)

        if not data.get("client_secret", {}).get("value"):
            logger.warning("Session created but client_secret.value is missing")

        return json_ok({
            "id": data.get("id"),
            "model": data.get("model"),
            "client_secret": data.get("client_secret"),
        })
    except AppError as e:
        return json_fail(e.message, status=e.status, details=e.details)


@csrf_exempt
@require_POST
def save_conversation(request):
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        messages = body.get("messages")
        
        if not isinstance(messages, list):
            return json_fail("Missing or invalid 'messages'", status=400)
        
        session_id = body.get("session_id")
        conv = Conversation.objects.create(session_id=session_id, messages=messages)
        
        return json_ok({
            "conversation_id": conv.pk,
            "created_at": conv.created_at.isoformat()
        })
    except Exception as exc:
        logger.exception("Failed saving conversation")
        return json_fail("Internal error", status=500, details=str(exc))


def _analyze_user_responses(messages: List[Dict[str, Any]], api_key: str, keys: List[str] = None) -> Dict[str, Any]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    if not keys:
        keys = ["name", "qualification", "experience"]
    
    json_schema = build_dynamic_schema(keys)
    
    payload = {
        "model": os.getenv("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "response_format": {"type": "json_schema", "json_schema": json_schema},
        "messages": build_extractor_messages(messages, keys),
    }
    
    data = post_json(url, headers, payload, timeout=30)
    
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        for k in keys:
            if k not in parsed:
                parsed[k] = ""
        return parsed
    except Exception:
        return {k: "" for k in keys}


@csrf_exempt
@require_POST
def analyze_conversation(request):
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
        session_id = body.get("session_id")
        
        if not session_id:
            return json_fail("session_id is required", status=400)
        
        conv = get_object_or_404(Conversation, session_id=session_id)
        api_key = require_env("OPENAI_API_KEY")
        
        extracted = _analyze_user_responses(conv.messages, api_key)
        conv.user_response = extracted
        conv.save(update_fields=["user_response", "updated_at"])
        
        return json_ok({"session_id": session_id, "user_response": extracted})
    except Exception as exc:
        logger.exception("Failed analyzing conversation")
        return json_fail("Analysis failed", status=500, details=str(exc))


def view_responses(request):
    conversations = Conversation.objects.filter(
        user_response__isnull=False
    ).exclude(user_response={}).order_by('-created_at')
    
    return render(request, "form_ai/responses.html", {
        "conversations": conversations
    })


@csrf_exempt
@require_POST
def generate_assessment(request, conv_id):
    """Generate assessment URL for a conversation"""
    try:
        conv = get_object_or_404(Conversation, id=conv_id)
        
        if not conv.user_response:
            return json_fail("No user response data", status=400)
        
        qualification = conv.user_response.get("qualification", "")
        experience = conv.user_response.get("experience", "")
        
        # Generate 3 expertise-based questions using GPT
        api_key = require_env("OPENAI_API_KEY")
        questions = _generate_expertise_questions(qualification, experience, api_key)
        
        assessment = Assessment.objects.create(
            conversation=conv,
            questions=questions
        )
        
        assessment_url = request.build_absolute_uri(
            f"/assessment/{assessment.id}/"
        )
        
        return json_ok({
            "assessment_id": str(assessment.id),
            "assessment_url": assessment_url,
            "questions": questions
        })
    except Exception as exc:
        logger.exception("Failed generating assessment")
        return json_fail("Failed to generate assessment", status=500, details=str(exc))


def _generate_expertise_questions(qualification: str, experience: str, api_key: str) -> List[Dict[str, str]]:
    """Use GPT to generate 3 relevant technical questions"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    prompt = f"""Generate exactly 3 technical interview questions for a candidate with:
- Qualification: {qualification}
- Experience: {experience}

Questions should be:
1. One fundamental concept question
2. One practical/scenario-based question
3. One advanced/problem-solving question

Return as JSON array: [{{"q": "question text"}}]"""

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    
    data = post_json(url, headers, payload, timeout=20)
    
    try:
        content = data["choices"][0]["message"]["content"]
        # Extract JSON from markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        questions = json.loads(content)
        return questions[:3]  # Ensure only 3 questions
    except Exception:
        # Fallback questions
        return [
            {"q": "Explain a fundamental concept in your field"},
            {"q": "Describe a practical project you've worked on"},
            {"q": "How would you solve a complex technical challenge?"}
        ]


def conduct_assessment(request, assessment_id):
    """Render assessment page"""
    assessment = get_object_or_404(Assessment, id=assessment_id)
    
    # Get user info from conversation
    user_info = assessment.conversation.user_response or {}
    
    return render(request, "form_ai/assessment.html", {
        "assessment": assessment,
        "assessment_id": str(assessment.id),
        "user_info": user_info
    })


@csrf_exempt
@require_POST
def save_assessment(request, assessment_id):
    """Save assessment conversation"""
    try:
        assessment = get_object_or_404(Assessment, id=assessment_id)
        body = json.loads(request.body.decode("utf-8") or "{}")
        
        messages = body.get("messages")
        if not isinstance(messages, list):
            return json_fail("Invalid messages", status=400)
        
        assessment.messages = messages
        assessment.save(update_fields=["messages", "updated_at"])
        
        return json_ok({"assessment_id": str(assessment.id)})
    except Exception as exc:
        logger.exception("Failed saving assessment")
        return json_fail("Save failed", status=500, details=str(exc))


@csrf_exempt
@require_POST
def analyze_assessment(request, assessment_id):
    """Analyze assessment responses"""
    try:
        assessment = get_object_or_404(Assessment, id=assessment_id)
        api_key = require_env("OPENAI_API_KEY")
        
        # Extract answers for each question
        answers = _extract_assessment_answers(
            assessment.messages,
            assessment.questions,
            api_key
        )
        
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


def _extract_assessment_answers(messages: List[Dict], questions: List[Dict], api_key: str) -> Dict:
    """Extract user answers from assessment conversation"""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    conversation_text = "\n".join([
        f"{m['role']}: {m['content']}" for m in messages
    ])
    
    questions_text = "\n".join([
        f"Q{i+1}: {q['q']}" for i, q in enumerate(questions)
    ])
    
    prompt = f"""Extract the user's answers to these questions from the conversation:

{questions_text}

Conversation:
{conversation_text}

Return JSON: {{"q1": "answer", "q2": "answer", "q3": "answer"}}"""

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }
    
    data = post_json(url, headers, payload, timeout=20)
    
    try:
        content = data["choices"][0]["message"]["content"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        return json.loads(content)
    except Exception:
        return {"q1": "", "q2": "", "q3": ""}