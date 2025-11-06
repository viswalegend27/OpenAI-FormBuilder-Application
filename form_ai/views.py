import json
import os
import logging
import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

def voice_page(request):
    """Render the voice assistant page"""
    return render(request, "form_ai/voice.html")

@csrf_exempt
def create_realtime_session(request):
    """
    Create an ephemeral Realtime session with OpenAI.
    Returns session JSON with client_secret.value for frontend auth.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("❌ Missing OPENAI_API_KEY environment variable")
        return JsonResponse({"error": "Server missing OPENAI_API_KEY"}, status=500)

    model = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview-2024-10-01")
    voice = os.getenv("OPENAI_REALTIME_VOICE", "verse")
    
    url = "https://api.openai.com/v1/realtime/sessions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": model,
        "voice": voice,
    }
    
    logger.info(f"🔑 Creating ephemeral session with model: {model}")
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        logger.info(f"📡 Session API response status: {resp.status_code}")
        
        if not resp.ok:
            error_text = resp.text
            logger.error(f"❌ Session creation failed ({resp.status_code}): {error_text}")
            try:
                error_json = resp.json()
                return JsonResponse({"error": "Session failed", "details": error_json}, status=resp.status_code)
            except:
                return JsonResponse({"error": "Session failed", "details": error_text}, status=resp.status_code)
        
        session_data = resp.json()
        session_id = session_data.get('id', 'unknown')
        logger.info(f"✅ Ephemeral session created: {session_id}")
        
        # Log if client_secret is missing (critical)
        if not session_data.get('client_secret', {}).get('value'):
            logger.error("⚠️ Session response missing client_secret.value!")
        
        return JsonResponse(session_data)
        
    except requests.exceptions.Timeout:
        logger.error("⏱️ Session creation timeout")
        return JsonResponse({"error": "Session request timeout"}, status=504)
    except requests.exceptions.RequestException as e:
        logger.exception("💥 Session request exception")
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("💥 Unexpected session exception")
        return JsonResponse({"error": str(e)}, status=500)