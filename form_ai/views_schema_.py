from typing import List, Dict, Any, Callable, Optional
import re
import json
import logging
from functools import wraps

from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from .helper.views_helper import AppError, json_fail, json_ok, post_json, require_env

logger = logging.getLogger(__name__)

# ============================================================================
# Schema Building
# ============================================================================

def extract_keys_from_markdown(md_text: str) -> List[str]:
    keys: List[str] = []
    for line in md_text.splitlines():
        m = re.match(r"^\s*-\s*Key:\s*([a-zA-Z0-9_\-]+)\s*$", line)
        if not m:
            continue
        key = m[1].strip().replace("-", "_")
        if key and key not in keys:
            keys.append(key)
    return keys


def build_dynamic_schema(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    properties: Dict[str, Dict[str, Any]] = {}
    required: List[str] = []

    for field in fields:
        key = field["key"]
        field_schema: Dict[str, Any] = {"type": "string"}
        description = field.get("description") or field.get("label")
        if description:
            field_schema["description"] = description
        properties[key] = field_schema

        if field.get("required", True):
            required.append(key)

    return {
        "name": "UserAnswers",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        },
        "strict": True,
    }


def build_extractor_messages(
    messages: List[Dict[str, Any]], fields: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    guide_lines = []
    for field in fields:
        label = field.get("label") or field["key"]
        description = field.get("description")
        if description and description != label:
            guide_lines.append(f"- {field['key']}: {description}")
        else:
            guide_lines.append(f"- {field['key']}: {label}")

    guide_text = "\n".join(guide_lines)
    system = (
        "Extract concise answers ONLY from what the USER said for the fields listed below.\n"
        "If the conversation does not provide the answer for a field, output an empty string for that key.\n"
        "Field guide:\n"
        f"{guide_text}"
    )
    user = json.dumps(messages, ensure_ascii=False)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ============================================================================
# Decorators
# ============================================================================

def handle_view_errors(error_message: str = "Operation failed"):
    """Decorator to handle common view errors and return JSON responses."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            try:
                return func(request, *args, **kwargs)
            except AppError as e:
                return json_fail(e.message, status=e.status, details=e.details)
            except Exception as exc:
                logger.exception(f"Failed in {func.__name__}")
                return json_fail(error_message, status=500, details=str(exc))
        return wrapper
    return decorator


# ============================================================================
# Request Utilities
# ============================================================================

def safe_json_parse(body: bytes) -> Dict[str, Any]:
    """Safely parse JSON from request body."""
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to parse request body: {e}")
        return {}


def validate_field(data: Dict, field: str, field_type: type, required: bool = True) -> Optional[Any]:
    """Validate a field exists and is of correct type."""
    value = data.get(field)
    
    if required and value is None:
        raise AppError(f"Missing required field: {field}", status=400)
    
    if value is not None and not isinstance(value, field_type):
        raise AppError(f"Invalid type for {field}", status=400)
    
    return value


def get_object_or_fail(model, **kwargs):
    """Get object or raise AppError instead of Http404."""
    try:
        return get_object_or_404(model, **kwargs)
    except Exception as e:
        raise AppError(f"{model.__name__} not found", status=404)


# ============================================================================
# OpenAI Client
# ============================================================================

class OpenAIClient:
    """Centralized OpenAI API client."""
    
    CHAT_URL = "https://api.openai.com/v1/chat/completions"
    REALTIME_URL = "https://api.openai.com/v1/realtime/sessions"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or require_env("OPENAI_API_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def create_realtime_session(self, payload: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
        """Create a realtime session."""
        tool_names = [tool.get("name") for tool in payload.get("tools", [])]
        logger.info(
            "[OPENAI] create_realtime_session -> model=%s, tools=%s, instructions_len=%d",
            payload.get("model"),
            tool_names,
            len(payload.get("instructions") or ""),
        )
        data = post_json(self.REALTIME_URL, self.headers, payload, timeout=timeout)

        if not data.get("client_secret", {}).get("value"):
            logger.warning("Session created but client_secret.value is missing")
        
        return {
            "id": data.get("id"),
            "model": data.get("model"),
            "client_secret": data.get("client_secret"),
        }
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        response_format: Optional[Dict] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """Make a chat completion request."""
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": messages,
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        return post_json(self.CHAT_URL, self.headers, payload, timeout=timeout)
    
    def extract_structured_data(
        self,
        messages: List[Dict[str, Any]],
        fields: List[Dict[str, Any]],
        model: str = "gpt-4o-mini"
    ) -> Dict[str, Any]:
        """Extract structured data from conversation messages."""
        json_schema = build_dynamic_schema(fields)
        
        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {
                "type": "json_schema",
                "json_schema": json_schema
            },
            "messages": build_extractor_messages(messages, fields),
        }
        
        data = post_json(self.CHAT_URL, self.headers, payload, timeout=30)
        
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return {field["key"]: parsed.get(field["key"], "") for field in fields}
        except (KeyError, json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse extraction response: {e}")
            return {field["key"]: "" for field in fields}
    
    @staticmethod
    def parse_response_content(content: str) -> Any:
        """Extract and parse JSON from response, handling markdown code blocks."""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return json.loads(content)


# ============================================================================
# Assessment Extraction Utilities
# ============================================================================

QUESTION_INTENT_SCHEMA = {
    "name": "InterviewQuestionIntents",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "label", "key", "summary"],
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "description": "Question ID"},
                        "label": {
                            "type": "string",
                            "description": "Short human-friendly name (max 4 words)",
                        },
                        "key": {
                            "type": "string",
                            "description": "snake_case field name derived from the label",
                        },
                        "summary": {
                            "type": "string",
                            "description": "One-sentence description of what this field captures",
                        },
                        "topic": {
                            "type": "string",
                            "description": "Primary competency or topic",
                        },
                    },
                },
            }
        },
        "required": ["fields"],
    },
        "strict": True,
}

QUESTION_INTENT_SYSTEM_PROMPT = """You are a taxonomy expert who turns interview questions into concise structured field definitions.
For each question, provide:
- label: Title-case 1-3 words summarizing the data being collected (no verbs, no leading question words, e.g., "Skill Set", "Preferred Languages").
- key: snake_case form of the label.
- summary: One short sentence explaining what should be captured.
- topic: (optional) core competency keyword (e.g., "Stack", "Communication").

Rules:
- Never repeat the original question text verbatim.
- Strip fillers like "What is your", "Can you describe", "Tell me about".
- Focus on the noun phrase that represents the answer.

Example question:
{"id": "123", "question": "What is your skill set?", "sequence": 1}

Example output object for that question:
{"id": "123", "label": "Skill Set", "key": "skill_set", "summary": "Primary technologies and frameworks the candidate can work with.", "topic": "Stack"}
"""


class QuestionIntentSummarizer:
    """Use LLM to identify the data each interview question tries to capture."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = None
        try:
            self.client = OpenAIClient(api_key)
        except AppError as exc:
            logger.info("[QUESTION_INTENT] Disabled summarizer: %s", exc)
            self.client = None

    def summarize(self, questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        if not questions:
            return {}
        if not self.client:
            return {}

        messages = [
            {"role": "system", "content": QUESTION_INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(questions, ensure_ascii=False)},
        ]

        try:
            data = self.client.chat_completion(
                messages=messages,
                temperature=0.1,
                response_format={
                    "type": "json_schema",
                    "json_schema": QUESTION_INTENT_SCHEMA,
                },
            )
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, AppError) as exc:
            logger.warning(f"[QUESTION_INTENT] Failed to summarize: {exc}")
            return {}

        results: Dict[str, Dict[str, str]] = {}
        for item in parsed.get("fields", []):
            qid = item.get("id")
            if not qid:
                continue
            results[qid] = {
                "label": item.get("label"),
                "key": item.get("key"),
                "summary": item.get("summary"),
                "topic": item.get("topic"),
            }
        return results




def get_recent_user_responses(limit: int = 10) -> List[Dict[str, Any]]:
    """Query database for recent user responses."""
    # Placeholder for actual implementation
    return []
