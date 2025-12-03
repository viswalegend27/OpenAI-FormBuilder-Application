# urls.py

from django.urls import path

from . import views

urlpatterns = [
    # Page views
    path("", views.interview_builder, name="interview_builder"),
    path("voice/<uuid:interview_id>/", views.voice_page, name="voice_page"),
    path("voice/invite/<str:token>/", views.voice_invite, name="voice_invite"),
    path("responses/", views.view_responses, name="view_responses"),
    # API endpoints
    path("api/interviews/", views.create_interview, name="create_interview"),
    path(
        "api/interviews/<uuid:interview_id>/",
        views.delete_interview,
        name="delete_interview",
    ),
    path(
        "api/interviews/<uuid:interview_id>/questions/<str:question_id>/",
        views.delete_interview_question,
        name="delete_interview_question",
    ),
    path(
        "api/interviews/<uuid:interview_id>/links/",
        views.create_voice_invite,
        name="create_voice_invite",
    ),
    path("api/session", views.create_realtime_session, name="create_realtime_session"),
    path("api/conversation/", views.save_conversation, name="save_conversation"),
    path(
        "api/conversation/analyze",
        views.analyze_conversation,
        name="analyze_conversation",
    ),
    # Response management
    path("responses/<int:conv_id>/view/", views.view_response, name="view_response"),
    path("responses/<int:conv_id>/edit/", views.edit_response, name="edit_response"),
    path(
        "responses/<int:conv_id>/delete/", views.delete_response, name="delete_response"
    ),
]
