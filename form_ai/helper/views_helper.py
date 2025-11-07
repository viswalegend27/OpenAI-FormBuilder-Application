import os
import logging
import requests
from django.http import JsonResponse

logger = logging.getLogger(__name__)

class AppError(Exception):
    # AppError is an custom exception to carry out finding the HTTP-friendly error
    def __init__(self, message: str, status: int = 500, details=None):
        super().__init__(message)
        self.message = message # Contains messages human readable error
        self.status = status # Sending out http status codes
        self.details = details # Optional details to include

# Used to wrap any HTTP resp as JSON 
def json_ok(payload, status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status, safe=False)

# Fallback methodology to know error status if json method fails.
def json_fail(message: str, status: int = 400, details=None) -> JsonResponse:
    body = {"error": message}
    if details is not None:
        body["details"] = details
    return JsonResponse(body, status=status, safe=False)

# Method to obtain and notify the user whether there is
def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise AppError(f"Missing required environment variable: {name}", status=500)
    return val

# post JSON to upstream API and normalize all errors into AppError
def post_json(url: str, headers: dict, payload: dict, timeout: int = 20) -> dict:
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        raise AppError("Upstream timeout", status=504)
    except requests.exceptions.RequestException as e:
        logger.exception("Upstream request exception")
        raise AppError("Upstream request error", status=502, details=str(e))

    if not resp.ok:
        try:
            # Parse for resp.json() for error details.
            details = resp.json()
        except Exception:
            # Executes this if the json parsing fails.
            details = resp.text
        raise AppError("OpenAI error", status=resp.status_code, details=details)

    try:
        return resp.json()
    except Exception:
        # Only sessions endpoint is used here; it should return JSON.
        raise AppError("Invalid JSON from OpenAI", status=502, details=resp.text[:800])