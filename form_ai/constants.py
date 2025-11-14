import os
import logging
from django.conf import settings

_INSTRUCTIONS_MD = settings.AI_INSTRUCTIONS_PATH

def _float_env(name: str, default: float = 0.6) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def _read_instructions_md() -> str:
    try:
        text = _INSTRUCTIONS_MD.read_text(encoding="utf-8").strip()
        return text or "Instruction file is empty."
    except Exception as e:
        logging.warning("Failed to read instructions: %s", e)
        return f"Error: Failed to read instructions ({e})"

def get_persona() -> str:
    return _read_instructions_md()

def get_session_payload() -> dict:
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

def get_assessment_persona(qualification: str, experience: str) -> str:
    """Generate assessment instructions based on user's expertise"""
    return f"""You are Tyler, Techjays' technical interviewer.

You are conducting a technical assessment for a candidate with:
- Qualification: {qualification}
- Experience: {experience}

Ask exactly 3 technical questions relevant to their expertise. Questions should be:
1. One fundamental concept question
2. One practical/scenario-based question  
3. One advanced/problem-solving question

Keep each question concise and wait for the answer before proceeding to the next.
After all 3 questions, thank them and end the assessment.
"""