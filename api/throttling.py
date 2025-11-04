"""
Custom rate limiting for API endpoints.
"""
from rest_framework.throttling import SimpleRateThrottle


class APITokenRateThrottle(SimpleRateThrottle):
    """
    Rate limiting based on API token.

    Uses token's custom rate_limit field if set, otherwise falls back to default.
    Rate limits are enforced per token, not per IP or user.

    Limits are specified in requests per hour.
    """

    scope = "api_token"

    def get_cache_key(self, request, view):
        """
        Generate cache key based on API token.

        Args:
            request: HTTP request object
            view: DRF view

        Returns:
            str or None: Cache key for throttling, None if not applicable
        """
        if not hasattr(request, "api_token"):
            return None  # Don't throttle session auth differently

        return f"throttle_api_token_{request.api_token.token}"

    def get_rate(self):
        """
        Override to use token's custom rate limit.

        Returns:
            str: Rate in format "1000/hour"
        """
        if hasattr(self, "request") and hasattr(self.request, "api_token"):
            token = self.request.api_token
            # Return custom rate: "1000/hour" format
            return f"{token.rate_limit}/hour"

        return super().get_rate()

    def allow_request(self, request, view):
        """
        Check if request should be allowed based on rate limit.

        Args:
            request: HTTP request object
            view: DRF view

        Returns:
            bool: True if request is allowed, False if throttled
        """
        # Store request for get_rate() access
        self.request = request
        return super().allow_request(request, view)
