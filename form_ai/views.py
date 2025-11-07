import logging
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .helper.views_helper import AppError, json_ok, json_fail, require_env, post_json
from . import constants as C

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