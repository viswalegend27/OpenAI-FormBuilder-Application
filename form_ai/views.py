import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from .helper.views_helper import AppError, json_ok, json_fail, require_env, post_json
from . import constants as C
import json
from django.views.decorators.http import require_POST
from .models import Conversation, InterviewForm, InterviewResponse
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
        return C.get_persona() 
    except Exception:
        return "No ai character"

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

def recent_responses(request):
    # Fetch recent user responses from the Conversation model
    recent_conversations = Conversation.objects.order_by('-created_at')[:10]  # Get the last 10 responses
    return render(request, "form_ai/responses.html", {"conversations": recent_conversations})

def view_recent_responses(request):
    """
    Display recent conversations that have been analyzed.
    Shows conversations with non-null and non-empty user_response.
    """
    # Get all conversations for debugging (optional)
    all_count = Conversation.objects.count()
    
    # Get analyzed conversations
    qs = (
        Conversation.objects
        .filter(user_response__isnull=False)
        .exclude(user_response={})
        .order_by('-created_at')[:20]
    )
    
    # Debug logging
    logger.info(f"Total conversations: {all_count}, Analyzed: {qs.count()}")
    
    return render(request, "form_ai/responses.html", {
        "conversations": qs,  # Fixed: was "conversations", template expected "responses"
        "total_count": all_count,
        "analyzed_count": qs.count(),
    })
    
def debug_all_conversations(request):
    """Debug view to see all conversations including unanalyzed ones"""
    qs = Conversation.objects.order_by('-created_at')[:20]

    conversations_data = []
    conversations_data.extend(
        {
            'id': conv.pk,
            'session_id': conv.session_id,
            'created_at': conv.created_at,
            'has_user_response': bool(
                conv.user_response and conv.user_response != {}
            ),
            'user_response': conv.user_response,
            'message_count': len(conv.messages) if conv.messages else 0,
        }
        for conv in qs
    )
    return render(request, "form_ai/debug_conversations.html", {
        "conversations": conversations_data
    })

# Create a new interview form
@csrf_exempt
def create_interview_form(request):
    """Creates a new interview form and returns the unique URL"""
    try:
        if request.method == "POST":
            body = json.loads(request.body.decode("utf-8") or "{}")
            title = body.get("title", "Internship Application")
            instructions = body.get("instructions", _load_instruction_text())
            expected_fields = body.get("expected_fields", ["name", "qualification", "experience"])
            
            form = InterviewForm.objects.create(
                title=title,
                instructions=instructions,
                expected_fields=expected_fields
            )
            
            return json_ok({
                "form_id": str(form.id),
                "interview_url": request.build_absolute_uri(form.get_interview_url()),
                "title": form.title
            })
        else:
            # GET request - create with defaults
            form = InterviewForm.objects.create(
                title="Internship Application",
                instructions=_load_instruction_text(),
                expected_fields=["name", "qualification", "experience"]
            )
            
            # Redirect to the form list or return JSON
            return redirect('manage_forms')
            
    except Exception as exc:
        logger.exception("Failed creating interview form")
        return json_fail("Failed to create form", status=500, details=str(exc))


# Render the interview page
def conduct_interview(request, form_id):
    """Renders the interview page for a specific form"""
    form = get_object_or_404(InterviewForm, id=form_id, is_active=True)
    
    return render(request, "form_ai/interview.html", {
        "form": form,
        "form_id": str(form.id)
    })


# Save interview conversation
@csrf_exempt
@require_POST
def save_interview_response(request, form_id):
    """Saves the interview conversation for a specific form"""
    try:
        form = get_object_or_404(InterviewForm, id=form_id)
        
        body = json.loads(request.body.decode("utf-8") or "{}")
        messages = body.get("messages")
        
        if not isinstance(messages, list):
            return json_fail("Invalid messages format", status=400)
        
        session_id = body.get("session_id")
        
        # Create interview response
        response = InterviewResponse.objects.create(
            form=form,
            session_id=session_id,
            messages=messages
        )
        
        return json_ok({
            "response_id": str(response.id),
            "created_at": response.created_at.isoformat()
        })
        
    except InterviewForm.DoesNotExist:
        return json_fail("Interview form not found", status=404)
    except Exception as exc:
        logger.exception("Failed saving interview response")
        return json_fail("Internal error", status=500, details=str(exc))
# Analyze interview response
@csrf_exempt
@require_POST
def analyze_interview_response(request, form_id):
    """Analyzes the interview conversation and extracts structured data"""
    try:
        form = get_object_or_404(InterviewForm, id=form_id)
        body = json.loads(request.body.decode("utf-8") or "{}")
        
        session_id = body.get("session_id")
        if not session_id:
            return json_fail("session_id required", status=400)
        
        # Find the response
        response = InterviewResponse.objects.filter(
            form=form,
            session_id=session_id
        ).order_by('-created_at').first()
        
        if not response:
            return json_fail("Interview response not found", status=404)
        
        # Analyze using the form's expected fields
        api_key = require_env("OPENAI_API_KEY")
        extracted = _analyze_user_responses(
            response.messages,
            api_key,
            keys=form.expected_fields
        )
        
        # Update response
        response.user_response = extracted
        response.completed = True
        response.save(update_fields=["user_response", "completed", "updated_at"])
        
        return json_ok({
            "response_id": str(response.id),
            "user_response": extracted
        })
        
    except Exception as exc:
        logger.exception("Failed analyzing interview")
        return json_fail("Analysis failed", status=500, details=str(exc))


# View all forms and their responses
def manage_forms(request):
    """Lists all interview forms and their responses"""
    forms = InterviewForm.objects.filter(is_active=True).prefetch_related('responses')
    
    forms_data = []
    for form in forms:
        forms_data.append({
            'form': form,
            'response_count': form.responses.count(),
            'completed_count': form.responses.filter(completed=True).count(),
            'interview_url': request.build_absolute_uri(form.get_interview_url())
        })
    
    return render(request, "form_ai/manage_forms.html", {
        "forms": forms_data
    })


# View responses for a specific form
def view_form_responses(request, form_id):
    """View all responses for a specific interview form"""
    form = get_object_or_404(InterviewForm, id=form_id)
    responses = InterviewResponse.objects.filter(
        form=form,
        completed=True,
        user_response__isnull=False
    ).exclude(user_response={}).order_by('-created_at')
    
    return render(request, "form_ai/form_responses.html", {
        "form": form,
        "responses": responses
    })