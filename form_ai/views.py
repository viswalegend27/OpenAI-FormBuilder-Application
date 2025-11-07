import os
import logging
import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

def voice_page(request):
    # Renders my html page. 
    return render(request, "form_ai/voice.html")

@csrf_exempt
def create_realtime_session(request):
    # Get API key and validate
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("❌ Missing OPENAI_API_KEY environment variable")
        return JsonResponse({"error": "Server missing OPENAI_API_KEY"}, status=500)

    # Load model and voice config
    model = os.getenv("OPENAI_REALTIME_MODEL")
    voice = os.getenv("OPENAI_REALTIME_VOICE")

    # Prepare API endpoint and headers
    url = "https://api.openai.com/v1/realtime/sessions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Prepare payload for session creation
    payload = {"model": model, "voice": voice}
    logger.info(f"🔑 Creating ephemeral session with model: {model}")

    try:
        # Send request to OpenAI Realtime API
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        logger.info(f"📡 Session API response status: {resp.status_code}")

        # Handle API failure response
        if not resp.ok:
            error_text = resp.text
            logger.error(f"❌ Session creation failed ({resp.status_code}): {error_text}")
            try:
                error_json = resp.json()
                return JsonResponse({"error": "Session failed", "details": error_json}, status=resp.status_code)
            except:
                return JsonResponse({"error": "Session failed", "details": error_text}, status=resp.status_code)

        # Extract and log session data
        session_data = resp.json()
        session_id = session_data.get('id', 'unknown')
        logger.info(f"✅ Ephemeral session created: {session_id}")

        # Warn if critical data missing
        if not session_data.get('client_secret', {}).get('value'):
            logger.error("⚠️ Session response missing client_secret.value!")

        # Return session data to client
        return JsonResponse(session_data)

    # Handle network or timeout errors
    except requests.exceptions.Timeout:
        logger.error("⏱️ Session creation timeout")
        return JsonResponse({"error": "Session request timeout"}, status=504)
    except requests.exceptions.RequestException as e:
        logger.exception("💥 Session request exception")
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("💥 Unexpected session exception")
        return JsonResponse({"error": str(e)}, status=500)
