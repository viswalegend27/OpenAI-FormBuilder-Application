from django.shortcuts import render
from .models import Conversation

def recent_user_responses(request):
    recent_responses = Conversation.objects.order_by('-created_at')[:10]  # Fetch the 10 most recent responses
    return render(request, "form_ai/responses.html", {"responses": recent_responses})