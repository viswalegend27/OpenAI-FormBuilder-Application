import os
import logging
import requests
from django.http import JsonResponse
from typing import Any, Dict

logger = logging.getLogger(__name__)

class AppError(Exception):
    # AppError is an custom exception to carry out finding the HTTP-friendly error
    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.message = message # Contains messages human readable error
        self.status = status # Sending out http status codes

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
    if val := os.getenv(name):
        return val
    else:
        raise AppError(f"Missing required environment variable: {name}", status=500)

# post JSON to upstream API and normalize all errors into AppError
def post_json(url: str, headers: dict, payload: dict, timeout: int = 20) -> Dict[str, Any]:
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.Timeout as exc:
        # upstream timed out
        raise AppError("Upstream timeout", status=504) from exc
    except requests.RequestException as exc:
        # network/transport level error
        logger.exception("Upstream request exception")
        raise AppError("Upstream request error", status=502, details=str(exc)) from exc

    # try to parse JSON once
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None

    if not resp.ok:
        # prefer structured JSON error details when available
        details = parsed if parsed is not None else resp.text
        raise AppError("OpenAI error", status=resp.status_code, details=details)

    if parsed is None:
        # success status but invalid JSON body
        raise AppError("Invalid JSON from OpenAI", status=502, details=resp.text[:800])

    return parsed