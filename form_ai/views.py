import logging
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .helper.views_helper import AppError, json_ok, json_fail, require_env, post_json
from . import constants as C
import json
from django.views.decorators.http import require_POST
from .models import Conversation
from .views_schema_ import (
    extract_keys_from_markdown,
    build_dynamic_schema,
    build_extractor_messages,
)
from typing import List, Dict, Any
import os

logger = logging.getLogger(__name__)

def voice_page(request):
    # Renders my html page. 
    return render(request, "form_ai/voice.html")

@csrf_exempt
def create_realtime_session(request):
    try:
        # Allow GET/POST only right now for testing the working of the code.
        if request.method not in ("GET", "POST"):
            return json_fail("Method not allowed", status=405)

        # Get API key and config
        api_key = require_env("OPENAI_API_KEY")

        # OpenAI Realtime session endpoint
        url = "https://api.openai.com/v1/realtime/sessions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Defining my payload logic
        payload = C.get_session_payload()
        # Creating my session along with the payload.
        data = post_json(url, headers, payload, timeout=20)

        # Warn if client_secret is missing (ephemeral key)
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
        if request.content_type != "application/json":
            # allow also other content types but prefer application/json
            try:
                body = json.loads(request.body.decode("utf-8") or "{}")
            except Exception:
                return json_fail("Expected JSON body", status=400)
        else:
            body = json.loads(request.body.decode("utf-8") or "{}")

        messages = body.get("messages")
        if messages is None or not isinstance(messages, list):
            return json_fail("Missing or invalid 'messages' (expecting list)", status=400)
        session_id = body.get("session_id")
        conv = Conversation.objects.create(
            session_id=session_id,
            messages=messages,
        )
        return json_ok({"conversation_id": conv.pk, "created_at": conv.created_at.isoformat()})

    except AppError as e:
        return json_fail(e.message, status=e.status, details=e.details)
    except Exception as exc:
        logger.exception("Failed saving conversation")
        return json_fail("Internal error saving conversation", status=500, details=str(exc))

def _load_instruction_text() -> str:
    # -- Where my AI person is loaded
    try:
        return C.get_persona() or ""
    except Exception:
        return ""

def _analyze_user_responses(messages: List[Dict[str, Any]], api_key: str, model: str = None, keys: List[str] | None = None) -> Dict[str, Any]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    model = model or os.getenv("OPENAI_ANALYSIS_MODEL", "gpt-4o-mini")
    # Determine keys dynamically from instructions if not provided
    if not keys:
        instruction_text = _load_instruction_text()
        keys = extract_keys_from_markdown(instruction_text)
    json_schema = build_dynamic_schema(keys)

    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_schema", "json_schema": json_schema},
        "messages": build_extractor_messages(messages, keys),
    }
    # Reuse helper to post and parse JSON
    data = post_json(url, headers, payload, timeout=30)
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        # Ensure all keys exist (fill missing with empty string)
        for k in keys:
            if k not in parsed:
                parsed[k] = ""
        return parsed
    except Exception:
        # Fallback: return empty structure
        return {k: "" for k in keys}


@csrf_exempt
@require_POST
def analyze_conversation(request):
    # -- Code used to analyze the save message for user_response
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return json_fail("Expected JSON body", status=400)

    session_id = body.get("session_id")
    if not session_id:
        return json_fail("session_id is required", status=400)

    try:
        conv = Conversation.objects.get(session_id=session_id)
    except Conversation.DoesNotExist:
        return json_fail("Conversation not found", status=404)

    api_key = require_env("OPENAI_API_KEY")
    messages = conv.messages or []
    if not isinstance(messages, list):
        return json_fail("Conversation messages is not a list", status=400)

    extracted = _analyze_user_responses(messages, api_key)
    conv.user_response = extracted
    conv.save(update_fields=["user_response", "updated_at"])

    return json_ok({"session_id": session_id, "user_response": extracted})
