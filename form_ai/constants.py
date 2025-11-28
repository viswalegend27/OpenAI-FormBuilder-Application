# constants.py

import logging
from pathlib import Path
from functools import lru_cache
from typing import Any, List, Sequence

from django.conf import settings

from .models import InterviewForm

logger = logging.getLogger(__name__)


# ============================================================================
# File Paths
# ============================================================================

_INSTRUCTIONS_PATH = settings.AI_INSTRUCTIONS_PATH


# ============================================================================
# File Reading
# ============================================================================


def _read_file(file_path: Path) -> str | None:
    """Read file content. Returns None on error."""
    try:
        content = file_path.read_text(encoding="utf-8").strip()
        return content if content else None
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")
        return None


def _format_questions(questions: Sequence[str]) -> str:
    """Format question list for prompt consumption."""
    return "\n".join(f"{idx}. {text}" for idx, text in enumerate(questions, start=1))


# ============================================================================
# Content Getters (Cached)
# ============================================================================


@lru_cache(maxsize=1)
def get_persona() -> str:
    """Get AI persona instructions."""
    content = _read_file(_INSTRUCTIONS_PATH)
    if not content:
        raise ValueError("Instructions file is missing or empty")
    return content


def clear_cache():
    """Clear cached content."""
    get_persona.cache_clear()


def _compose_voice_instructions(
    question_texts: Sequence[str],
    role_label: str,
    custom_prompt: str = "",
) -> str:
    """Compose realtime instructions shared by custom and fallback flows."""
    question_list = [q.strip() for q in question_texts if q and q.strip()]
    if not question_list:
        raise ValueError("No valid interview questions were supplied")

    persona = get_persona()
    prompt = (custom_prompt or "").strip()
    if prompt:
        persona = f"{persona}\n\nAdditional guidance:\n{prompt}"

    question_count = len(question_list)
    questions_formatted = _format_questions(question_list)

    return f"""{persona}

You are interviewing a candidate for the {role_label} position. Follow this structure:
- Start by collecting baseline profile data. Confirm their full name, highest qualification (degree, specialization, graduation year), and total years of relevant experience (0 is valid). If these items already exist in the plan, you can cover them when that question arrives; otherwise ask them upfront so you can summarise and verify accurately.
- Let them know you have {question_count} additional question(s) and work through the plan below one question at a time, waiting for their response before moving on.
- Briefly restate or confirm each answer so the candidate knows you captured it correctly.

Questions to ask:
{questions_formatted}

After the final question, provide a concise summary of their answers. Ask if they'd like to verify or correct their details, and when they confirm call the `verify_information` tool with the latest name, qualification, and experience before thanking them for their time."""


# ============================================================================
# Session Configuration
# ============================================================================


def get_session_payload() -> dict:
    """Get OpenAI realtime session configuration."""
    return {
        "model": settings.OPENAI_REALTIME_MODEL,
        "voice": settings.OPENAI_REALTIME_VOICE,
        "instructions": get_persona(),
        "temperature": settings.OPENAI_REALTIME_TEMPERATURE,
        "input_audio_transcription": {
            "model": settings.TRANSCRIBE_MODEL,
        },
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.8,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 1000,
        },
        "tools": [],  # Will be populated dynamically per interview
        "tool_choice": "auto",
    }


def build_verify_tool(fields: List[dict[str, Any]]) -> dict:
    """Build dynamic verify_information tool based on interview questions."""
    properties: dict[str, dict[str, str]] = {}
    required: List[str] = []

    for field in fields:
        key = field["key"]
        description = field.get("description") or field.get("label") or key
        properties[key] = {
            "type": "string",
            "description": description,
        }
        if field.get("required", True):
            required.append(key)

    return {
        "type": "function",
        "name": "verify_information",
        "description": "Show verification popup for user to confirm their information",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def get_assessment_questions_for_role(role: str) -> List[str]:
    """Retrieve assessment questions dynamically from database for a role."""
    from .models import AssessmentQuestionBank

    questions = AssessmentQuestionBank.get_questions_for_role(role)
    if not questions:
        logger.warning(f"No assessment questions found for role: {role}")
        return []
    return questions


# ============================================================================
# Assessment Configuration
# ============================================================================


def get_assessment_persona(
    qualification: str,
    experience: str,
    questions: List[str] | None = None,
) -> str:
    """Generate assessment instructions for technical interview."""
    if not questions:
        raise ValueError("Assessment questions must be provided from the database")

    question_list = [q.strip() for q in questions if q and q.strip()]
    if not question_list:
        raise ValueError("No valid assessment questions were supplied")
    questions_formatted = _format_questions(question_list)

    return f"""You are Tyler, Techjays' technical interviewer.

You are conducting a technical assessment for a candidate with:
- Qualification: {qualification}
- Experience: {experience}

Ask these questions one by one:
{questions_formatted}

Keep each question concise and wait for the answer before proceeding to the next.
After all questions are answered, thank them and end the assessment."""


def build_interview_instructions(interview: InterviewForm) -> str:
    """Construct realtime persona instructions for a given interview form."""
    question_texts = interview.question_texts()
    if not question_texts:
        raise ValueError(
            f"Interview form '{interview.id}' does not have any questions configured"
        )

    role = interview.role or interview.title
    return _compose_voice_instructions(
        question_texts,
        role,
        custom_prompt=interview.ai_prompt or "",
    )
