# models.py

import uuid

from django.db import models
from django.utils import timezone


class InterviewForm(models.Model):
    """
    Interview template with ordered questions stored in the database.

    Relationships:
        - One InterviewForm -> Many InterviewQuestion
        - One InterviewForm -> Many VoiceConversation
        - One InterviewForm -> Many TechnicalAssessment
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, help_text="Internal name for the interview")
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

    def ordered_questions(self):
        """Return queryset ordered by sequence number."""
        return self.questions.order_by("sequence_number")

    def question_texts(self):
        """Return list of question strings."""
        return list(self.ordered_questions().values_list("question_text", flat=True))


class InterviewQuestion(models.Model):
    """Stores an individual interview question."""

    form = models.ForeignKey(
        InterviewForm,
        on_delete=models.CASCADE,
        related_name="questions",
        help_text="Parent interview definition",
    )
    sequence_number = models.PositiveIntegerField(help_text="Display order (1, 2, 3, ...)")
    question_text = models.TextField(help_text="Question content")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "interview_questions"
        ordering = ["sequence_number"]
        unique_together = ["form", "sequence_number"]
        verbose_name = "Interview Question"
        verbose_name_plural = "Interview Questions"

    def __str__(self):
        return f"{self.form.title} / Q{self.sequence_number}"


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
        - One TechnicalAssessment → Many AssessmentQuestions

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
    conversation = models.ForeignKey(
        VoiceConversation,
        on_delete=models.CASCADE,
        related_name="assessments",
        help_text="Parent conversation",
    )
    transcript = models.JSONField(
        default=list, help_text="Assessment conversation transcript"
    )
    qa_snapshot = models.JSONField(
        default=list, blank=True, help_text="Snapshot of questions and answers"
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

    @property
    def total_questions(self):
        """Total number of questions."""
        return self.questions.count()

    @property
    def answered_count(self):
        """Count of answered questions."""
        return (
            self.questions.filter(answer__isnull=False)
            .exclude(answer__response_text="NIL")
            .exclude(answer__response_text="")
            .count()
        )

    @property
    def completion_percentage(self):
        """Calculate completion percentage."""
        total = self.total_questions
        return round((self.answered_count / total * 100), 1) if total else 0

    def get_qa_pairs(self):
        """Get all question-answer pairs for display."""
        pairs = []
        for question in self.questions.select_related("answer").all():
            pairs.append(
                {
                    "number": question.sequence_number,
                    "question": question.question_text,
                    "answer": (
                        question.answer.response_text
                        if hasattr(question, "answer")
                        else "NIL"
                    ),
                    "answered_at": (
                        question.answer.created_at
                        if hasattr(question, "answer")
                        else None
                    ),
                }
            )
        return pairs


class AssessmentQuestion(models.Model):
    """
    Individual question in a technical assessment.

    Relationships:
        - Many AssessmentQuestions → One TechnicalAssessment
        - One AssessmentQuestion → One CandidateAnswer (optional)
    """

    assessment = models.ForeignKey(
        TechnicalAssessment,
        on_delete=models.CASCADE,
        related_name="questions",
        help_text="Parent assessment",
    )
    sequence_number = models.PositiveIntegerField(
        help_text="Question order (1, 2, 3...)"
    )
    question_text = models.TextField(help_text="The question content")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_questions"
        ordering = ["sequence_number"]
        unique_together = ["assessment", "sequence_number"]
        verbose_name = "Assessment Question"
        verbose_name_plural = "Assessment Questions"

    def __str__(self):
        return f"Q{self.sequence_number}: {self.question_text[:50]}..."

    @property
    def is_answered(self):
        """Check if this question has been answered."""
        return hasattr(self, "answer") and self.answer.is_valid


class CandidateAnswer(models.Model):
    """
    Candidate's answer to an assessment question.

    Relationships:
        - One CandidateAnswer → One AssessmentQuestion (OneToOne)
    """

    question = models.OneToOneField(
        AssessmentQuestion,
        on_delete=models.CASCADE,
        related_name="answer",
        help_text="The question being answered",
    )
    response_text = models.TextField(
        default="NIL", blank=True, help_text="Candidate's response"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "candidate_answers"
        verbose_name = "Candidate Answer"
        verbose_name_plural = "Candidate Answers"

    def __str__(self):
        return f"Answer to Q{self.question.sequence_number}"

    @property
    def is_valid(self):
        """Check if answer has meaningful content."""
        return bool(
            self.response_text
            and self.response_text.strip()
            and self.response_text.strip() != "NIL"
        )

    @classmethod
    def create_or_update(cls, question, text):
        """Create or update answer for a question."""
        answer_text = text.strip() if text and text.strip() else "NIL"
        answer, created = cls.objects.update_or_create(
            question=question, defaults={"response_text": answer_text}
        )
        return answer, created
