# constants.py
import os
import logging
from typing import List, Dict
from django.conf import settings

logger = logging.getLogger(__name__)

# ============================================================================
# File Paths
# ============================================================================

_INSTRUCTIONS_MD = settings.AI_INSTRUCTIONS_PATH
_QUESTIONS_MD = settings.AI_QUESTIONS_PATH


# ============================================================================
# Utility Functions
# ============================================================================

def _float_env(name: str, default: float = 0.6) -> float:
    """Safely parse float from environment variable."""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _read_file(file_path, file_type: str = "file") -> str:
    """Read and return file content with error handling."""
    try:
        text = file_path.read_text(encoding="utf-8").strip()
        return text or f"{file_type.capitalize()} file is empty."
    except Exception as e:
        logger.warning(f"Failed to read {file_type}: {e}")
        return f"Error: Failed to read {file_type} ({e})"


# ============================================================================
# Instructions
# ============================================================================

def get_persona() -> str:
    """Get AI persona instructions from markdown file."""
    return _read_file(_INSTRUCTIONS_MD, "instructions")


# ============================================================================
# Questions
# ============================================================================

def get_questions() -> List[Dict[str, str]]:
    """
    Parse questions from markdown file.
    Expected format:
        1. Question one?
        2. Question two?
        3. Question three?
    
    Returns:
        List of dictionaries with 'q' key containing question text
    """
    content = _read_file(_QUESTIONS_MD, "questions")
    
    if content.startswith("Error:"):
        logger.warning("Using fallback questions due to file read error")
        return []
    
    questions = []
    for line in content.split('\n'):
        line = line.strip()
        # Match numbered questions: "1. Question text"
        if line and line[0].isdigit() and '. ' in line:
            question_text = line.split('. ', 1)[1].strip()
            if question_text:
                questions.append({"q": question_text})
    
    return questions


def get_questions_text() -> str:
    """Get raw questions text from markdown file."""
    return _read_file(_QUESTIONS_MD, "questions")


# ============================================================================
# Session Configuration
# ============================================================================

def get_session_payload() -> dict:
    """Get OpenAI realtime session configuration."""
    return {
        "model": os.getenv("OPENAI_REALTIME_MODEL"),
        "voice": os.getenv("OPENAI_REALTIME_VOICE"),
        "instructions": get_persona(),
        "temperature": _float_env("OPENAI_REALTIME_TEMPERATURE", 0.6),
        "input_audio_transcription": {
            "model": os.getenv("TRANSCRIBE_MODEL"),
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
    """
    Generate assessment instructions for technical interview.
    
    Args:
        qualification: Candidate's qualification
        experience: Candidate's experience level
    
    Returns:
        Formatted instruction string for AI interviewer
    """
    questions = get_questions()
    
    if questions:
        questions_list = "\n".join([f"{i+1}. {q['q']}" for i, q in enumerate(questions)])
        questions_section = f"\nAsk these questions one by one:\n{questions_list}"
    else:
        questions_section = "\nAsk 3 technical Python questions relevant to their expertise."
    
    return f"""You are Tyler, Techjays' technical interviewer.

You are conducting a technical assessment for a candidate with:
- Qualification: {qualification}
- Experience: {experience}
{questions_section}

Keep each question concise and wait for the answer before proceeding to the next.
After all questions are answered, thank them and end the assessment.
"""