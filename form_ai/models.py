from django.db import models
from django.utils import timezone

class Conversation(models.Model):
    session_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    messages = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
    def __str__(self):
        return f"Conversation {self.pk} session={self.session_id} messages={len(self.messages)}"
