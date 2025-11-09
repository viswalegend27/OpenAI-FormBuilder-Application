import logging
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .helper.views_helper import AppError, json_ok, json_fail, require_env, post_json
from . import constants as C
import json
from django.views.decorators.http import require_POST
from .models import Conversation

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

        return json_ok(data)
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
        conv = Conversation.objects.create(
            messages=messages,
        )
        return json_ok({"conversation_id": conv.pk, "created_at": conv.created_at.isoformat()})

    except AppError as e:
        return json_fail(e.message, status=e.status, details=e.details)
    except Exception as exc:
        logger.exception("Failed saving conversation")
        return json_fail("Internal error saving conversation", status=500, details=str(exc))
