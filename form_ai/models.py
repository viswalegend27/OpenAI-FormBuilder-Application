from django.db import models
from django.utils import timezone
import uuid


class Conversation(models.Model):
    """
    Stores conversation data from voice interactions.
    Each conversation contains messages and extracted user responses.
    """
    session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="Unique session identifier for tracking conversations"
    )
    messages = models.JSONField(
        help_text="Raw conversation messages between user and AI"
    )
    user_response = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="Extracted structured data (name, qualification, experience)"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"

    def __str__(self):
        return f"Conversation {self.pk} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class Assessment(models.Model):
    """
    Represents an assessment session linked to a conversation.
    Questions and answers are stored in separate related tables.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    # ForeignKey is on Assessment → Each Assessment points to ONE Conversation
    conversation = models.ForeignKey(
        # Points to one conversation. Each assessment points to 1 conversation
        Conversation,
        # This is my many (N) side which holds the foreign key.
        on_delete=models.CASCADE,
        # Each Conversation can access MULTIPLE Assessments
        related_name='assessments',
        help_text="Parent conversation that triggered this assessment"
    )
    messages = models.JSONField(
        default=list,
        help_text="Conversation messages during assessment"
    )
    completed = models.BooleanField(
        default=False,
        help_text="Whether all questions have been answered"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Assessment"
        verbose_name_plural = "Assessments"

    def __str__(self):
        return f"Assessment {self.id} - Conversation {self.conversation_id}"

    @property
    def total_questions(self):
        """Returns total number of questions in this assessment."""
        return self.questions.count()

    @property
    def answered_questions(self):
        """Returns count of answered questions that have non-empty answers."""
        return self.questions.filter(
            answer__isnull=False
        ).exclude(
            answer__data__answer_text=""
        ).count()

    @property
    def completion_percentage(self):
        """Calculate assessment completion percentage."""
        total = self.total_questions
        if total == 0:
            return 0
        return (self.answered_questions / total) * 100


class Question(models.Model):
    """
    Individual question within an assessment.
    Stores question data as JSONB.
    
    Data format: {"question_number": 1, "question_text": "..."}
    """
    # Assessment is the foreignKey
    assessment = models.ForeignKey(
        # Each question to point to one assessment
        Assessment,
        on_delete=models.CASCADE,
        # Pointing towards the questions.
        related_name='questions',
        help_text="Assessment this question belongs to"
    )
    data = models.JSONField(
        help_text="Question data stored as JSONB"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['data__question_number']
        verbose_name = "Question"
        verbose_name_plural = "Questions"
        indexes = [
            models.Index(fields=['assessment']),
        ]

    def __str__(self):
        question_num = self.data.get('question_number', '?')
        question_text = self.data.get('question_text', 'No text')
        return f"Q{question_num}: {question_text[:50]}..."

    @property
    def question_number(self):
        """Get question number from JSONB data."""
        return self.data.get('question_number')

    @property
    def question_text(self):
        """Get question text from JSONB data."""
        return self.data.get('question_text', '')


class Answer(models.Model):
    """
    Answer to a specific question.
    Stores answer data as JSONB.
    
    Data format: {"answer_text": "...", "question_number": 1}
    """
    # Here where 1 : 1 (has answer) relationship is initiated.
    question = models.OneToOneField(
        Question,
        on_delete=models.CASCADE,
        # Singular name 1 : 1 (Question) : (Answer)
        related_name='answer',
        help_text="Question this answer responds to"
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Answer data stored as JSONB"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Answer"
        verbose_name_plural = "Answers"

    def __str__(self):
        question_num = self.question.question_number
        return f"Answer to Q{question_num}"

    @property
    def answer_text(self):
        """Get answer text from JSONB data."""
        return self.data.get('answer_text', '')

    @property
    def is_answered(self):
        """Check if this answer has content."""
        answer_text = self.answer_text
        return bool(answer_text and str(answer_text).strip())
