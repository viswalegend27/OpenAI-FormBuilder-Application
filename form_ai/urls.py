from django.urls import path
from . import views

urlpatterns = [
    path("", views.voice_page, name="voice_page"),
    path("api/session", views.create_realtime_session, name="create_realtime_session"),
    path("api/conversation/", views.save_conversation, name="save_conversation"),
    path("api/conversation/analyze", views.analyze_conversation, name="analyze_conversation"),
    path("responses/", views.view_responses, name="view_responses"),
    path("responses/<int:conv_id>/generate-assessment/", views.generate_assessment, name="generate_assessment"),
    path("assessment/<uuid:assessment_id>/", views.conduct_assessment, name="conduct_assessment"),
    path("assessment/<uuid:assessment_id>/save/", views.save_assessment, name="save_assessment"),
    path("assessment/<uuid:assessment_id>/analyze/", views.analyze_assessment, name="analyze_assessment"),
    path('responses/<int:conv_id>/edit/', views.edit_response, name='edit_responses'),
    path('responses/<int:conv_id>/delete/', views.delete_response, name='delete_responses'),
]