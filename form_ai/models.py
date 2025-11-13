from django.db import models
from django.utils import timezone
import uuid


class Conversation(models.Model):
    session_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    messages = models.JSONField()
    # Store structured answers extracted by AI for the 10-question flow
    user_response = models.JSONField(default=dict, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
    def __str__(self):
        return f"Conversation {self.pk} session={self.session_id} messages={len(self.messages)}"

class InterviewForm(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, default="Internship Application")
    instructions = models.TextField(default="")  # AI persona instructions
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, blank=True)  # Optional: track who created it
    is_active = models.BooleanField(default=True)
    
    # Optional: store expected fields
    expected_fields = models.JSONField(default=list)  # e.g., ["name", "qualification", "experience"]
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} ({self.id})"
    
    def get_interview_url(self):
        from django.urls import reverse
        return reverse('conduct_interview', kwargs={'form_id': str(self.id)})


class InterviewResponse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(InterviewForm, on_delete=models.CASCADE, related_name='responses')
    session_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Conversation data
    messages = models.JSONField(default=list)
    user_response = models.JSONField(default=dict, blank=True, null=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Response to {self.form.title} - {self.created_at}"