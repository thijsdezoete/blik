"""
WSGI application for landing/marketing site only.

This is a minimal Django application that only serves the landing app
without database, authentication, or other Django features.
"""
import os
from django.core.wsgi import get_wsgi_application

# Point to landing-specific settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'landing_settings')

application = get_wsgi_application()
