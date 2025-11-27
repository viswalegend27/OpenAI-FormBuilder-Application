# constants.py

import os
import logging
from pathlib import Path
from functools import lru_cache
from typing import List, Sequence, Optional

from django.conf import settings

from .models import InterviewForm

logger = logging.getLogger(__name__)


# ============================================================================
# File Paths
# ============================================================================

_INSTRUCTIONS_PATH = settings.AI_INSTRUCTIONS_PATH
_QUESTIONS_PATH = settings.AI_QUESTIONS_PATH


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


def _parse_numbered_list(content: str) -> List[str]:
    """Parse numbered list into list of strings."""
    items = []
    for line in content.split('\n'):
        line = line.strip()
        if line and line[0].isdigit() and '. ' in line:
            text = line.split('. ', 1)[1].strip()
            if text:
                items.append(text)
    return items


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


@lru_cache(maxsize=1)
def get_questions() -> List[str]:
    """
    Get assessment questions as list of strings.
    
    Returns:
        List of question text strings: ["Question 1?", "Question 2?", ...]
    """
    content = _read_file(_QUESTIONS_PATH)
    if not content:
        raise ValueError("Questions file is missing or empty")
    
    questions = _parse_numbered_list(content)
    if not questions:
        raise ValueError("No valid questions found")
    
    return questions


def clear_cache():
    """Clear cached content."""
    get_persona.cache_clear()
    get_questions.cache_clear()


# ========================================================================
# Voice Interview Defaults
# ========================================================================

DEFAULT_VOICE_QUESTIONS: List[str] = [
    "What is your full name?",
    "What is your highest qualification? (e.g., B.E. Computer Science 2025)",
    "How many years of relevant experience do you have?",
]


def get_default_voice_questions() -> List[str]:
    """Return a copy of the fallback voice interview questions."""
    return list(DEFAULT_VOICE_QUESTIONS)


def _compose_voice_instructions(
    question_texts: Sequence[str],
    role_label: str,
    custom_prompt: str = "",
    context_note: Optional[str] = None,
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
    question_label = "questions" if question_count != 1 else "question"
    questions_formatted = _format_questions(question_list)
    context_section = f"{context_note}\n\n" if context_note else ""

    return f"""{persona}

{context_section}You are interviewing a candidate for the {role_label} position. Follow this structure:
- Greet the candidate and explain that you will ask {question_count} {question_label}
- Ask the questions one at a time, waiting for their answer before moving on
- Briefly confirm each answer so the candidate knows you captured it

Questions to ask:
{questions_formatted}

After the final question, provide a concise summary of their answers, offer verification, and thank them."""


def build_default_voice_instructions() -> str:
    """Return instructions for the fallback interview flow."""
    return _compose_voice_instructions(
        get_default_voice_questions(),
        "internship screening",
        context_note="Use this default plan only when no custom interview form ID is provided.",
    )


# ============================================================================
# Session Configuration
# ============================================================================

def _get_env(name: str, default: str = '') -> str:
    return os.getenv(name, default)


def _get_float(name: str, default: float = 0.6) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def get_session_payload() -> dict:
    """Get OpenAI realtime session configuration."""
    return {
        "model": _get_env("OPENAI_REALTIME_MODEL"),
        "voice": _get_env("OPENAI_REALTIME_VOICE"),
        "instructions": get_persona(),
        "temperature": _get_float("OPENAI_REALTIME_TEMPERATURE", 0.6),
        "input_audio_transcription": {
            "model": _get_env("TRANSCRIBE_MODEL"),
        },
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.8,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 1000
        },
        "tools": [
            {
                "type": "function",
                "name": "verify_information",
                "description": "Show verification popup for user to confirm their information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "User's full name"},
                        "qualification": {"type": "string", "description": "User's qualification"},
                        "experience": {"type": "string", "description": "User's experience"}
                    },
                    "required": ["name", "qualification", "experience"]
                }
            }
        ],
        "tool_choice": "auto"
    }


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
