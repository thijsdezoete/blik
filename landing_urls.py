"""
URL configuration for landing container.

Serves landing pages at root paths instead of /landing/ prefix.
Imports URL patterns from landing.urls WITHOUT the namespace (no app_name).
This allows templates using {% landing_url %} to work correctly in standalone mode.
"""
from landing.urls import urlpatterns
