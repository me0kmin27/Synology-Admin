from django.urls import path

from config.views import health, landing

urlpatterns = [path("", landing), path("health/", health)]
