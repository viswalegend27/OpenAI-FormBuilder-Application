# OpenAI Voice Assistant (Django + WebRTC)

A Django 5.x app that serves a browser-based, voice-to-voice assistant using OpenAI’s Realtime API over WebRTC. The page captures your microphone, negotiates a peer connection with OpenAI, and plays back the assistant’s audio responses.

## Features
- Django project with app `form_ai`
- Static assets split by type: `form_ai/static/form_ai/{css,js}`
- Template: `form_ai/templates/form_ai/voice.html`
- WebRTC client that:
	- Creates SDP offer
	- Gets an ephemeral session key from your backend
	- Posts the offer directly to OpenAI Realtime
	- Applies SDP answer and streams audio
- Backend endpoints:
	- `GET /` or `/voice/` — Voice UI page
	- `GET /api/session` — Creates OpenAI Realtime ephemeral session
	- `POST /api/realtime/offer/` — Legacy proxy (not used by the current UI)

## Prerequisites
- Python 3.11+ (3.13 supported)
- pip, venv
- OpenAI API key with Realtime access
- For the current DB settings: a running PostgreSQL (or switch to SQLite for quick local dev)

## Quickstart (Windows PowerShell)
```powershell
cd "D:\Viswa\Techjays - Intern Projects\Voice-assistant form builder"
# (Optional) create/activate venv if not created
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
# If requirements.txt is incomplete:
# pip install django python-dotenv requests

# Run database migrations (PostgreSQL expected by current settings.py)
python manage.py migrate

# Start server
python manage.py runserver
```
Open http://127.0.0.1:8000/ and click “Start voice session”.

## Environment variables (.env)
Create a `.env` at the project root (same folder as `manage.py`):
```
DJANGO_KEY=your-django-secret-key
OPENAI_API_KEY=sk-...
OPENAI_REALTIME_MODEL=gpt-realtime                # or gpt-4o-realtime-preview
OPENAI_REALTIME_VOICE=verse                       # optional
TRANSCRIBE_MODEL=whisper-1                        # optional

# Current DB settings expect PostgreSQL:
DB_NAME=ai_form_database
DB_USER=ai_form_user
DB_PASSWORD=your-password
DB_HOST=localhost
DB_PORT=5432
```
Notes:
- `.env` is loaded by `formbuilder/settings.py` via `python-dotenv`.
- Do NOT commit your API key. Rotate it if it was exposed.

## How it works (end-to-end)
1. Browser requests the page (`/` or `/voice/`) and loads `voice.js`.
2. When you click “Start”, the browser:
	 - Gets microphone permission
	 - Creates an RTCPeerConnection and a data channel
	 - Creates a local SDP offer and waits briefly for ICE gathering
	 - Calls `GET /api/session` to create an ephemeral OpenAI Realtime session
	 - Sends the local SDP offer directly to `https://api.openai.com/v1/realtime?model=...` with the ephemeral key
	 - Receives the SDP answer (as text), sanitizes it for strict browsers, and sets it as remote description
	 - Plays the remote audio stream from OpenAI
3. The assistant processes your audio and streams audio responses back over the peer connection.

## Key files
- Page: `form_ai/templates/form_ai/voice.html`
- Client: `form_ai/static/form_ai/js/voice.js`
	- WebRTC setup
	- Ephemeral session fetch (`/api/session`)
	- SDP sanitization (drops TCP candidates and non-standard tokens causing parse errors)
- Server routes: `form_ai/urls.py`
	- `/` and `/voice/` → page
	- `/api/session` → ephemeral session JSON
	- `/api/realtime/offer/` → legacy Realtime proxy (not required by current UI)
- Settings: `formbuilder/settings.py` (loads `.env`, uses PostgreSQL by default)

## Troubleshooting
- “Invalid SDP line” when setting remote description:
	- The client sanitizes the SDP answer by:
		- Dropping all TCP candidates
		- Stripping non-standard tokens (`ufrag`, `network-id`, `network-cost`) on UDP candidates
	- This resolves common browser parsing issues for ICE-lite answers.
- 401/403 from OpenAI:
	- Ensure `OPENAI_API_KEY` is valid and entitled for Realtime
	- Some accounts require org/project headers; add them if needed in the server code for session creation
- 400 from OpenAI:
	- Try another realtime model:
		- `OPENAI_REALTIME_MODEL=gpt-realtime`
		- or `gpt-4o-realtime-preview`
- Mic not working:
	- Allow microphone permission in the browser
	- On localhost, `getUserMedia` is permitted without HTTPS

## Optional: switch to SQLite for quick local dev
If you don’t want to run Postgres locally:
- In `formbuilder/settings.py`, change the default DB to SQLite:
```python
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
```
- Then run:
```powershell
python manage.py migrate
python manage.py runserver
```

## Security
- Keep `.env` out of version control.
- Rotate `OPENAI_API_KEY` if it was ever exposed.
- Use HTTPS and a production-grade ASGI/WSGI server for deployment.

## License
This project uses OpenAI services. Ensure your usage complies with OpenAI’s Terms of Use.
