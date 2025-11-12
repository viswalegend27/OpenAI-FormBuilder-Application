from typing import List, Dict, Any
import re
import json

def extract_keys_from_markdown(md_text: str) -> List[str]:
	keys: List[str] = []
	for line in md_text.splitlines():
		m = re.match(r"^\s*-\s*Key:\s*([a-zA-Z0-9_\-]+)\s*$", line)
		if not m:
			continue
		key = m[1].strip().replace("-", "_")
		if key and key not in keys:
			keys.append(key)
	return keys


def build_dynamic_schema(keys: List[str]) -> Dict[str, Any]:
	return {
		"name": "UserAnswers",
		"schema": {
			"type": "object",
			"additionalProperties": False,
			"properties": {k: {"type": "string"} for k in keys},
			"required": keys,
		},
		"strict": True,
	}


def build_extractor_messages(messages: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, str]]:
	system = (
		"Extract concise answers ONLY from what the USER said for these keys: "
		+ ", ".join(keys)
		+ ". Return JSON that strictly matches the provided schema."
	)
	user = json.dumps(messages, ensure_ascii=False)
	return [
		{"role": "system", "content": system},
		{"role": "user", "content": user},
	]

def get_recent_user_responses(limit: int = 10) -> List[Dict[str, Any]]:
    # This function should query the database for recent user responses
    # and return them in a structured format.
    # Placeholder for actual implementation.
    return []  # Intentionally left blank for now.