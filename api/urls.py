"""
API URL configuration.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from .viewsets import (
    RevieweeViewSet,
    ReviewCycleViewSet,
    QuestionnaireViewSet,
    ReportViewSet,
    WebhookEndpointViewSet,
    APITokenViewSet,
)

# Create router for viewsets
router = DefaultRouter()
router.register(r"reviewees", RevieweeViewSet, basename="reviewee")
router.register(r"cycles", ReviewCycleViewSet, basename="cycle")
router.register(r"questionnaires", QuestionnaireViewSet, basename="questionnaire")
router.register(r"reports", ReportViewSet, basename="report")
router.register(r"webhooks", WebhookEndpointViewSet, basename="webhook")
router.register(r"tokens", APITokenViewSet, basename="api-token")

app_name = "api"

urlpatterns = [
    # API endpoints
    path("", include(router.urls)),
    # OpenAPI schema
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    # API documentation UIs
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="api:schema"),
        name="swagger-ui",
    ),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),
]
