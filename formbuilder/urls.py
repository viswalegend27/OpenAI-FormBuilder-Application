from django.contrib import admin
from django.urls import include,path
from django.shortcuts import redirect
from django.templatetags.static import static

def favicon_redirect(request):
    return redirect(static("form_ai/favicon.ico"), permanent=True)

urlpatterns = [
    path('admin/', admin.site.urls),
    path("favicon.ico", favicon_redirect),
    path("", include("form_ai.urls")),
]
