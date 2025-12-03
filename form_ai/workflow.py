# workflow.py

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from django.db import transaction

from .helper.views_helper import AppError
from .models import InterviewForm, VoiceConversation, build_question_entry

logger = logging.getLogger(__name__)

# Auto-generated starter interview template used when the workspace is empty.
REQUIRED_SECTION_TITLE = "Candidate Basics"
REQUIRED_QUESTIONS = [
    {
        "text": "To start, could you please share your full name as you'd like it recorded?",
        "field_key": "name",
    },
    {
        "text": "What is your highest qualification and in which year did you graduate?",
        "field_key": "qualification",
    },
    {
        "text": "How many years of relevant experience do you have in the field you are applying for?",
        "field_key": "experience",
    },
]

STARTER_INTERVIEW_TEMPLATE = {
    "title": "Sample Interview Plan",
    "sections": [
        {
            "title": "Projects",
            "questions": [
                "Walk me through a project where you had to solve a complex problem.",
                "What part of that project are you most proud of?",
                "How did you collaborate with your team during this project?",
            ],
        },
        {
            "title": "Technical Depth",
            "questions": [
                "Which technologies are you most comfortable with today?",
                "Tell me about a debugging challenge that taught you something new.",
            ],
        },
    ],
}


class InterviewFlow:
    """Operations tied to InterviewForm nodes."""

    @staticmethod
    def create_form(
        *,
        title: str,
        sections: Iterable[Mapping[str, Any]] | None,
    ) -> InterviewForm:
        title_value = (title or "").strip()
        if not title_value:
            raise AppError("Interview title is required", status=400)

        custom_sections = InterviewFlow._normalize_sections(sections)
        custom_entries = InterviewFlow._build_section_entries(custom_sections)
        if not custom_entries:
            raise AppError("Add at least one interview question section", status=400)

        question_entries = InterviewFlow._build_required_entries() + custom_entries

        interview = InterviewForm.objects.create(
            title=title_value,
        )
        interview.set_question_entries(question_entries)
        interview.save(update_fields=["question_schema", "updated_at"])
        logger.info(
            "[FLOW:INTERVIEW] Created interview %s with %d questions",
            interview.id,
            len(question_entries),
        )
        return interview

    @staticmethod
    def delete_form(form: InterviewForm) -> Dict[str, Any]:
        question_count = len(form.get_question_entries())
        title = form.title
        interview_id = str(form.id)
        form.delete()
        remaining = InterviewForm.objects.count()
        logger.info(
            "[FLOW:INTERVIEW] Deleted interview %s (%s) with %d questions",
            interview_id,
            title,
            question_count,
        )
        return {
            "interview_id": interview_id,
            "title": title,
            "deleted_questions": question_count,
            "remaining_interviews": remaining,
        }

    @staticmethod
    def remove_question(form: InterviewForm, question_id: str) -> int:
        questions = form.get_question_entries()
        if len(questions) <= 1:
            raise AppError(
                "At least one question is required per interview. Add another question before deleting this one.",
                status=400,
            )

        entry = next((item for item in questions if str(item["id"]) == str(question_id)), None)
        if not entry:
            raise AppError("Question not found on this interview", status=404)

        metadata = entry.get("metadata") or {}
        if metadata.get("locked"):
            raise AppError("Required onboarding questions cannot be removed", status=400)

        if not form.remove_question(question_id):
            raise AppError("Question not found on this interview", status=404)

        form.save(update_fields=["question_schema", "updated_at"])
        remaining = len(form.get_question_entries())
        logger.info(
            "[FLOW:INTERVIEW] Removed question %s from interview %s (remaining=%d)",
            question_id,
            form.id,
            remaining,
        )
        return remaining

    @staticmethod
    def required_section_template() -> Dict[str, Any]:
        """Return a serializable definition of the protected basics section."""
        return {
            "title": REQUIRED_SECTION_TITLE,
            "locked": True,
            "questions": [item["text"] for item in REQUIRED_QUESTIONS],
        }

    @staticmethod
    def to_section_groups(entries: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """Group flat question entries by their section metadata."""
        sections: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            metadata = entry.get("metadata") or {}
            section_title = metadata.get("section") or "Questions"
            bucket = sections.setdefault(
                section_title,
                {
                    "title": section_title,
                    "locked": bool(metadata.get("locked")),
                    "questions": [],
                },
            )
            bucket["questions"].append(entry)
        return list(sections.values())

    @staticmethod
    def _normalize_sections(sections: Iterable[Mapping[str, Any]] | None) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not sections:
            return normalized

        for section in sections:
            if not isinstance(section, Mapping):
                continue
            title = str(section.get("title") or "").strip()
            questions = section.get("questions")
            if isinstance(questions, (str, bytes)) or not isinstance(questions, Iterable):
                continue
            cleaned_questions = []
            for question in questions:
                if isinstance(question, str):
                    text = question.strip()
                else:
                    text = str(question or "").strip()
                if text:
                    cleaned_questions.append(text)
            if cleaned_questions:
                normalized.append({"title": title or "Untitled section", "questions": cleaned_questions})
        return normalized

    @staticmethod
    def _build_required_entries() -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for item in REQUIRED_QUESTIONS:
            metadata = {
                "section": REQUIRED_SECTION_TITLE,
                "locked": True,
                "field_key": item.get("field_key"),
            }
            entries.append(build_question_entry(item["text"], metadata=metadata))
        return entries

    @staticmethod
    def _build_section_entries(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for section in sections:
            for text in section["questions"]:
                metadata = {"section": section["title"]}
                entries.append(build_question_entry(text, metadata=metadata))
        return entries

    @staticmethod
    def ensure_seed_interview() -> InterviewForm | None:
        """Create a starter interview when none exist so the UI always has content."""
        if InterviewForm.objects.exists():
            return None

        template = STARTER_INTERVIEW_TEMPLATE
        try:
            interview = InterviewFlow.create_form(
                title=template["title"],
                sections=template.get("sections"),
            )
            logger.info("[FLOW:INTERVIEW] Seeded starter interview %s", interview.id)
            return interview
        except AppError as exc:
            logger.error("[FLOW:INTERVIEW] Failed to seed starter interview: %s", exc)
        except Exception as exc:  # pragma: no cover - safety log
            logger.exception("[FLOW:INTERVIEW] Unexpected error seeding interview: %s", exc)
        return None


class ConversationFlow:
    """Operations tied to VoiceConversation nodes."""

    @staticmethod
    def save_conversation(
        *,
        messages: List[Dict[str, Any]],
        session_id: str | None,
        interview_form: InterviewForm | None,
    ) -> VoiceConversation:
        conversation = VoiceConversation.objects.create(
            session_id=session_id,
            messages=messages,
            interview_form=interview_form,
        )
        logger.info(
            "[FLOW:CONVERSATION] Stored conversation %s (messages=%d, interview=%s)",
            conversation.pk,
            len(messages),
            interview_form.id if interview_form else "-",
        )
        return conversation

    @staticmethod
    def apply_analysis(conversation: VoiceConversation, extracted_data: Mapping[str, Any]) -> VoiceConversation:
        conversation.extracted_info = dict(extracted_data or {})
        conversation.save(update_fields=["extracted_info", "updated_at"])
        logger.info(
            "[FLOW:CONVERSATION] Analysis saved for %s with fields: %s",
            conversation.pk,
            ", ".join(conversation.extracted_info.keys()),
        )
        return conversation


