"""
Custom exception handling for API.
"""
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.exceptions import ValidationError, PermissionDenied, NotAuthenticated
from django.core.exceptions import ObjectDoesNotExist
import logging

logger = logging.getLogger("api")


def custom_exception_handler(exc, context):
    """
    Custom exception handler for DRF.

    Provides better error messages and logging for API errors.

    Args:
        exc: Exception instance
        context: Context dict with view and request info

    Returns:
        Response object with error details
    """
    # Call DRF's default exception handler first
    response = drf_exception_handler(exc, context)

    # Log the error
    if response is not None:
        request = context.get("request")
        view = context.get("view")

        log_data = {
            "status_code": response.status_code,
            "error": str(exc),
            "path": request.path if request else None,
            "method": request.method if request else None,
            "view": view.__class__.__name__ if view else None,
        }

        if response.status_code >= 500:
            logger.error(f"API Server Error: {log_data}")
        elif response.status_code >= 400:
            logger.warning(f"API Client Error: {log_data}")

        # Add error code to response
        if isinstance(exc, ValidationError):
            response.data["error_code"] = "validation_error"
        elif isinstance(exc, PermissionDenied):
            response.data["error_code"] = "permission_denied"
        elif isinstance(exc, NotAuthenticated):
            response.data["error_code"] = "not_authenticated"
        elif isinstance(exc, ObjectDoesNotExist):
            response.data["error_code"] = "not_found"

    return response
