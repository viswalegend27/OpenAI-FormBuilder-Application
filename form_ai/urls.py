# urls.py

from django.urls import path

from . import views

urlpatterns = [
    # Page views
    path("", views.interview_builder, name="interview_builder"),
    path("voice/<uuid:interview_id>/", views.voice_page, name="voice_page"),
    path("responses/", views.view_responses, name="view_responses"),
    path(
        "assessment/<str:token>/", views.conduct_assessment, name="conduct_assessment"
    ),
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
    path(
        "responses/<int:conv_id>/generate-assessment/",
        views.generate_assessment,
        name="generate_assessment",
    ),
    path(
        "assessments/<uuid:assessment_id>/",
        views.delete_assessment,
        name="delete_assessment",
    ),
    # Assessment endpoints
    path(
        "assessment/<str:assessment_id>/save/",
        views.save_assessment,
        name="save_assessment",
    ),
    path(
        "assessment/<str:assessment_id>/analyze/",
        views.analyze_assessment,
        name="analyze_assessment",
    ),
]
