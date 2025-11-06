from django.urls import path
from .views import voice_page, create_realtime_session

urlpatterns = [
    path("", voice_page, name="home"),
    path("voice/", voice_page, name="voice_page"),
    path("api/session", create_realtime_session, name="create_realtime_session"),
]