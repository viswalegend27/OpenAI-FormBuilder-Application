import json
import logging
from typing import Any, Dict, Optional
import requests
from django.conf import settings
from django.http import JsonResponse, HttpRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

# Constants / defaults
OPENAI_SESSIONS_URL = "https://api.openai.com/v1/realtime/sessions"
REQUEST_TIMEOUT_SECONDS = 20

def voice_page(request: HttpRequest):
    # --- Main logic: render the template for the voice assistant UI
    return render(request, "form_ai/voice.html")


@csrf_exempt
@require_POST
def create_realtime_session(request: HttpRequest) -> JsonResponse:
    # --- Main logic: obtain API key and model/voice configuration
    api_key: Optional[str] = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        # fallback to environment variable (kept for compatibility)
        import os

        api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        logger.error("❌ Missing OPENAI_API_KEY environment variable or Django setting.")
        return JsonResponse({"error": "Server missing OPENAI_API_KEY"}, status=500)

    # Load configurable defaults from settings with safe fallbacks
    model: str = getattr(settings, "OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-10-01")
    voice: str = getattr(settings, "OPENAI_REALTIME_VOICE", "verse")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": model,
        "voice": voice,
    }

    logger.info("🔑 Creating ephemeral session (model=%s, voice=%s)", model, voice)

    # --- Main logic: perform the POST request to OpenAI's realtime sessions endpoint
    try:
        with requests.Session() as session:
            resp = session.post(
                OPENAI_SESSIONS_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        logger.info("📡 Session API response status: %s", resp.status_code)

        # Try to parse the response body as JSON (capture body on failure)
        try:
            session_data = resp.json()
        except json.JSONDecodeError:
            text_body = resp.text[:2000]  # limit how much we log
            logger.error("❌ Session creation returned non-JSON response (status %s). Body: %s", resp.status_code, text_body)
            return JsonResponse({"error": "Session returned non-JSON response", "details": text_body}, status=resp.status_code)

        if not resp.ok:
            # If the API returned an error status, forward the JSON (if any) to the client
            logger.error("❌ Session creation failed (%s): %s", resp.status_code, session_data)
            return JsonResponse({"error": "Session failed", "details": session_data}, status=resp.status_code)

        # --- Main logic: validate session response structure and warn if missing keys
        client_secret = None
        if isinstance(session_data, dict):
            client_secret_obj = session_data.get("client_secret")
            if isinstance(client_secret_obj, dict):
                client_secret = client_secret_obj.get("value")

        if not client_secret:
            # Warning — client_secret.value is required for frontend auth but we don't redact the response here.
            # We log a warning so maintainers can debug, but do not leak any sensitive contents into logs.
            logger.warning("⚠️ Session response does not contain client_secret.value; frontend may not be able to authenticate.")

        # Return the whole session object to the frontend (frontend should read client_secret.value)
        return JsonResponse(session_data)

    except requests.exceptions.Timeout:
        logger.error("⏱️ Session creation timeout after %s seconds", REQUEST_TIMEOUT_SECONDS)
        return JsonResponse({"error": "Session request timeout"}, status=504)
    except requests.exceptions.RequestException as e:
        # Network / connection level errors
        logger.exception("💥 Session request exception: %s", str(e))
        return JsonResponse({"error": "Request exception", "details": str(e)}, status=500)
    except Exception as e:
        # Unexpected errors: log stack trace and return generic message
        logger.exception("💥 Unexpected session exception")
        return JsonResponse({"error": "Unexpected server error", "details": str(e)}, status=500)
