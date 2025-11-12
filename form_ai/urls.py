from django.urls import path
from . import views
from .views import voice_page, create_realtime_session, view_recent_responses

urlpatterns = [
    path("", voice_page, name="home"),
    path("voice/", voice_page, name="voice_page"),
    path("api/session", create_realtime_session, name="create_realtime_session"),
    path("api/conversation/", views.save_conversation, name="save_conversation"),
    path("api/conversation/analyze", views.analyze_conversation, name="analyze_conversation"),
    path("responses/", view_recent_responses, name="view_recent_responses"),
]