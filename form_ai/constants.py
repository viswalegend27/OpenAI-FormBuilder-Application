# constants.py

import os
import logging
from pathlib import Path
from typing import List
from functools import lru_cache
from django.conf import settings

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

def get_assessment_persona(qualification: str, experience: str) -> str:
    """Generate assessment instructions for technical interview."""
    questions = get_questions()
    questions_formatted = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))

    return f"""You are Tyler, Techjays' technical interviewer.

You are conducting a technical assessment for a candidate with:
- Qualification: {qualification}
- Experience: {experience}

Ask these questions one by one:
{questions_formatted}

Keep each question concise and wait for the answer before proceeding to the next.
After all questions are answered, thank them and end the assessment."""