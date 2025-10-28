"""
URL configuration for landing container.

Serves landing pages at root paths instead of /landing/ prefix.
Imports the same URL patterns from landing.urls to maintain consistency.
"""
from landing.urls import urlpatterns
