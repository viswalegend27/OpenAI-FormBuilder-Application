# urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Page views
    path('', views.voice_page, name='voice_page'),
    path('responses/', views.view_responses, name='view_responses'),
    path('assessment/<str:token>/', views.conduct_assessment, name='conduct_assessment'),
    
    # API endpoints
    path('api/session', views.create_realtime_session, name='create_realtime_session'),
    path('api/save', views.save_conversation, name='save_conversation'),
    path('api/analyze', views.analyze_conversation, name='analyze_conversation'),
    
    # Response management
    path('responses/<int:conv_id>/view/', views.view_response, name='view_response'),
    path('responses/<int:conv_id>/edit/', views.edit_response, name='edit_response'),
    path('responses/<int:conv_id>/delete/', views.delete_response, name='delete_response'),
    path('responses/<int:conv_id>/generate-assessment/', views.generate_assessment, name='generate_assessment'),
    
    # Assessment endpoints
    path('assessment/<str:assessment_id>/save/', views.save_assessment, name='save_assessment'),
    path('assessment/<str:assessment_id>/analyze/', views.analyze_assessment, name='analyze_assessment'),
]