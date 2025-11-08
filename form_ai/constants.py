import os
import logging
from pathlib import Path

OPENAI_BETA_HEADER_VALUE = "realtime=v1"

# Setting an variable to point towards the ai_instructions.md
_INSTRUCTIONS_MD = Path(__file__).resolve().parent / "ai_instructions.md"

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
    if md := _read_instructions_md():
        return md

def get_session_payload() -> dict:
    return {
        "model": os.getenv("OPENAI_REALTIME_MODEL"),
        "voice": os.getenv("OPENAI_REALTIME_VOICE"),
        "instructions": get_persona(),
        "temperature": _float_env("OPENAI_REALTIME_TEMPERATURE", 0.6),
        "input_audio_transcription": {
            "model": os.getenv("TRANSCRIBE_MODEL"),
        },
    }