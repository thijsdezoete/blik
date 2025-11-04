"""
Custom API token authentication for DRF.
"""
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.utils import timezone
from .models import APIToken


class APITokenAuthentication(BaseAuthentication):
    """
    Bearer token authentication for API clients.

    Clients should authenticate by passing the token in the Authorization header.
    Example: Authorization: Bearer <token>

    Security features:
    - Token expiration support
    - Auto-update last_used_at timestamp
    - Organization context attachment
    - Active status check
    """

    def authenticate(self, request):
        """
        Authenticate the request using Bearer token.

        Args:
            request: HTTP request object

        Returns:
            Tuple of (user, token) if authentication successful, None otherwise

        Raises:
            AuthenticationFailed: If token is invalid, expired, or inactive
        """
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return None

        if not auth_header.startswith("Bearer "):
            return None

        token_value = auth_header[7:]  # Remove "Bearer " prefix

        try:
            token = APIToken.objects.select_related("organization", "created_by").get(
                token=token_value, is_active=True
            )
        except APIToken.DoesNotExist:
            raise AuthenticationFailed("Invalid or inactive token")

        # Check expiration
        if token.is_expired:
            raise AuthenticationFailed("Token has expired")

        # Update last used timestamp (using update to avoid triggering save signal)
        APIToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())

        # Attach organization to request (for middleware compatibility)
        request.organization = token.organization
        request.api_token = token

        # Return (user, auth) tuple - use token's creator as user
        # If no creator, use a system user or None (DRF will handle)
        return (token.created_by, token)

    def authenticate_header(self, request):
        """
        Return authentication challenge header for 401 responses.
        """
        return "Bearer"
