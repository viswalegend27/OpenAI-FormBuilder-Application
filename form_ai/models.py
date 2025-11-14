from django.db import models
from django.utils import timezone
import uuid


class Conversation(models.Model):
    session_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    messages = models.JSONField()
    user_response = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Conversation {self.pk} - {self.created_at}"


class Assessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='assessments')
    questions = models.JSONField()  # 3 expertise-based questions
    messages = models.JSONField(default=list)
    answers = models.JSONField(default=dict, blank=True, null=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Assessment {self.id} for Conv {self.conversation_id}"