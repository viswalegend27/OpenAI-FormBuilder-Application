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
    # New Interview Form URLs
    path("forms/", views.manage_forms, name="manage_forms"),
    path("forms/create/", views.create_interview_form, name="create_interview_form"),
    path("forms/<uuid:form_id>/responses/", views.view_form_responses, name="view_form_responses"),
    # Interview Conduct URLs
    path("interview/<uuid:form_id>/", views.conduct_interview, name="conduct_interview"),
    path("interview/<uuid:form_id>/save/", views.save_interview_response, name="save_interview_response"),
    path("interview/<uuid:form_id>/analyze/", views.analyze_interview_response, name="analyze_interview_response"),
]