import os
from pathlib import Path

OPENAI_BETA_HEADER_VALUE = "realtime=v1"

# Resolve path to the Markdown instructions file (same app folder)
_INSTRUCTIONS_MD = Path(__file__).resolve().parent / "ai_instructions.md"

def _float_env(name: str, default: float = 0.6) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def _read_instructions_md() -> str:
    try:
        text = _INSTRUCTIONS_MD.read_text(encoding="utf-8").strip()
        return text if text else ""
    except Exception:
        return ""

def get_persona() -> str:
    # Prefer Markdown file over any env-based text
    md = _read_instructions_md()
    if md:
        return md

    # Fallback: composed concise persona
    ai_name = "Tyler"
    role = "Techjays company intern hiring manager"
    domain = "applicant skill inquiries and form building based on given instructions"

    lines = [
        f"You are {ai_name}, a {role}.",
        f"Your goal is to guide users through {domain}.",
        "Ask one short question at a time, confirm details, and avoid long monologues.",
        "Keep answers under two sentences unless clarification is needed.",
        "Be polite, on-topic, and summarize key choices when appropriate.",
    ]
    return " ".join(lines)

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