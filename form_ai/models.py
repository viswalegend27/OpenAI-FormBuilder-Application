# models.py

import uuid
from typing import Any

from django.db import models
from django.utils import timezone


def build_question_entry(
    text: str,
    *,
    sequence: int | None = None,
    question_type: str = "text",
    metadata: dict | None = None,
    options: list | None = None,
    question_id: str | None = None,
) -> dict:
    """Create a normalized question entry stored inside JSON blobs."""
    return {
        "id": question_id or str(uuid.uuid4()),
        "sequence_number": sequence,
        "text": (text or "").strip(),
        "type": question_type or "text",
        "metadata": metadata or {},
        "options": options or [],
    }


def normalize_question_entries(entries: list[dict] | None) -> list[dict]:
    """Ensure every question entry has expected keys."""
    normalized: list[dict] = []
    if not isinstance(entries, list):
        entries = []

    for idx, entry in enumerate(entries, start=1):
        if isinstance(entry, str):
            entry = {"text": entry}
        elif not isinstance(entry, dict):
            entry = {"text": str(entry)}
        entry = entry or {}
        normalized.append(
            {
                "id": entry.get("id") or str(uuid.uuid4()),
                "sequence_number": entry.get("sequence_number") or idx,
                "text": (entry.get("text") or entry.get("question") or "").strip(),
                "type": entry.get("type") or entry.get("question_type") or "text",
                "metadata": entry.get("metadata") or {},
                "options": entry.get("options") or [],
            }
        )
    return normalized


def default_question_payload():
    """Backward-compatible payload builder referenced by historical migrations."""
    return {
        "text": "",
        "type": "text",
        "metadata": {},
        "options": [],
    }


class QuestionListMixin(models.Model):
    """Abstract helper that stores ordered question definitions inline as JSON."""

    question_schema = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered question definitions stored inline (JSON list of {id, sequence_number, text, type, metadata, options})",
    )

    class Meta:
        abstract = True

    def get_question_entries(self) -> list[dict]:
        """Return normalized question dictionaries with enforced ordering."""
        entries = normalize_question_entries(self.question_schema)
        for idx, entry in enumerate(entries, start=1):
            entry["sequence_number"] = idx
        return entries

    def set_question_entries(self, entries: list[dict]) -> None:
        """Persist normalized question entries."""
        normalized = normalize_question_entries(entries)
        for idx, entry in enumerate(normalized, start=1):
            entry["sequence_number"] = idx
        self.question_schema = normalized

    def question_texts(self) -> list[str]:
        """Return ordered question text list."""
        return [entry.get("text", "") for entry in self.get_question_entries()]

    def append_questions(self, texts: list[str]) -> None:
        """Extend the schema with plain text questions."""
        current = self.get_question_entries()
        next_index = len(current) + 1
        for text in texts:
            if not text or not str(text).strip():
                continue
            current.append(build_question_entry(str(text).strip(), sequence=next_index))
            next_index += 1
        self.question_schema = current

    def remove_question(self, question_id: str) -> bool:
        """Drop a question by its identifier."""
        current = self.get_question_entries()
        filtered = [entry for entry in current if entry["id"] != str(question_id)]
        if len(filtered) == len(current):
            return False
        for idx, entry in enumerate(filtered, start=1):
            entry["sequence_number"] = idx
        self.question_schema = filtered
        return True


class InterviewForm(QuestionListMixin, models.Model):
    """
    Interview template with ordered questions stored in the database.

    Relationships:
        - One InterviewForm -> Many VoiceConversation
        - One InterviewForm -> Many TechnicalAssessment
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(
        max_length=255, help_text="Internal name for the interview"
    )
    role = models.CharField(
        max_length=255,
        blank=True,
        help_text="Role or track this interview targets (e.g., Python Intern)",
    )
    summary = models.TextField(
        blank=True, help_text="Short description shown on the builder page"
    )
    ai_prompt = models.TextField(
        blank=True,
        help_text="Optional custom instructions appended to the base AI persona",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "interview_forms"
        ordering = ["-updated_at"]
        verbose_name = "Interview Form"
        verbose_name_plural = "Interview Forms"

    def __str__(self):
        return self.title

    def ordered_questions(self) -> list[dict]:
        """Return ordered JSON question entries."""
        return self.get_question_entries()

    def question_texts(self) -> list[str]:
        """Return list of question strings."""
        return super().question_texts()


class VoiceConversation(models.Model):
    """
    Stores voice conversation data from user interactions.

    Relationships:
        - One VoiceConversation → Many TechnicalAssessments

    JSONB Fields:
        - messages: List of conversation messages
        - extracted_info: {name, qualification, experience}
    """

    interview_form = models.ForeignKey(
        InterviewForm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
        help_text="Interview template used for this conversation",
    )
    session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Unique session identifier",
    )
    messages = models.JSONField(default=list, help_text="Raw conversation messages")
    extracted_info = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extracted user data: {name, qualification, experience}",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "voice_conversations"
        ordering = ["-created_at"]
        verbose_name = "Voice Conversation"
        verbose_name_plural = "Voice Conversations"

    def __str__(self):
        return f"Conversation #{self.pk} - {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def candidate_name(self):
        return self.extracted_info.get("name", "")

    @property
    def candidate_qualification(self):
        return self.extracted_info.get("qualification", "")

    @property
    def candidate_experience(self):
        return self.extracted_info.get("experience", "")


class TechnicalAssessment(models.Model):
    """
    Technical assessment session for a candidate.

    Relationships:
        - Many TechnicalAssessments → One VoiceConversation
        - One TechnicalAssessment → One CandidateAnswer sheet

    JSONB Fields:
        - transcript: Assessment conversation history
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    interview_form = models.ForeignKey(
        InterviewForm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessments",
        help_text="Interview template that supplied the questions",
    )
    questions = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered question text prompts for this assessment",
    )
    conversation = models.ForeignKey(
        VoiceConversation,
        on_delete=models.CASCADE,
        related_name="assessments",
        help_text="Parent conversation",
    )
    transcript = models.JSONField(
        default=list, help_text="Assessment conversation transcript"
    )
    is_completed = models.BooleanField(
        default=False, db_index=True, help_text="Whether assessment is finished"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "technical_assessments"
        ordering = ["-created_at"]
        verbose_name = "Technical Assessment"
        verbose_name_plural = "Technical Assessments"

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"Assessment {self.id} - {status}"

    def question_list(self) -> list[str]:
        """Return clean question text list."""
        cleaned: list[str] = []
        for item in self.questions or []:
            text = (str(item).strip() if item is not None else "")
            if text:
                cleaned.append(text)
        return cleaned

    def set_questions(self, texts: list[str]) -> None:
        """Persist ordered question text prompts."""
        cleaned: list[str] = []
        for text in texts or []:
            normalized = (str(text).strip() if text is not None else "")
            if normalized:
                cleaned.append(normalized)
        self.questions = cleaned

    def get_question_entries(self) -> list[dict[str, Any]]:
        """Return normalized question dictionaries for downstream callers."""
        entries: list[dict[str, Any]] = []
        for idx, text in enumerate(self.question_list(), start=1):
            entries.append(
                {
                    "id": f"q{idx}",
                    "sequence_number": idx,
                    "text": text,
                }
            )
        return entries

    @property
    def total_questions(self):
        """Total number of questions."""
        return len(self.question_list())

    @property
    def answered_count(self):
        """Count of answered questions."""
        if not hasattr(self, "answer_sheet"):
            return 0
        return sum(
            1
            for value in (self.answer_sheet.answers or {}).values()
            if isinstance(value, str) and value.strip() and value.strip().upper() != "NIL"
        )

    @property
    def completion_percentage(self):
        """Calculate completion percentage."""
        total = self.total_questions
        return round((self.answered_count / total * 100), 1) if total else 0

    def get_qa_pairs(self):
        """Get all question-answer pairs for display."""
        answers = (self.answer_sheet.answers if hasattr(self, "answer_sheet") else {}) or {}
        entries = []
        for question in self.get_question_entries():
            entry = {
                "number": question["sequence_number"],
                "question": question["text"],
                "answer": answers.get(question["id"]) or "NIL",
            }
            entries.append(entry)
        return entries


class CandidateAnswer(models.Model):
    """
    Candidate's answers stored per assessment as a JSON mapping.

    Relationships:
        - One CandidateAnswer → One TechnicalAssessment (OneToOne)
    """

    assessment = models.OneToOneField(
        TechnicalAssessment,
        on_delete=models.CASCADE,
        related_name="answer_sheet",
        help_text="Parent technical assessment",
        null=True,
        blank=True,
    )
    answers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Question key (e.g., q1, q2) mapped to normalized answer text",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "candidate_answers"
        verbose_name = "Candidate Answer Sheet"
        verbose_name_plural = "Candidate Answer Sheets"

    def __str__(self):
        return f"Answers for assessment {self.assessment_id}"

    def record_answer(self, question_id: str, text: str | None):
        """Insert/update an answer keyed by question identifier."""
        answers = dict(self.answers or {})
        normalized_key = str(question_id)
        normalized_text = (text or "").strip() or "NIL"
        answers[normalized_key] = normalized_text
        self.answers = answers
        self.save(update_fields=["answers", "updated_at"])

    def get_answer(self, question_id: str, default: str = "NIL") -> str:
        answers = self.answers or {}
        return answers.get(str(question_id), default)

    def answered_count(self) -> int:
        answers = self.answers or {}
        return sum(
            1
            for value in answers.values()
            if isinstance(value, str)
            and value.strip()
            and value.strip().upper() != "NIL"
        )


