"""
Context processors for landing app.

Provides URL namespace handling for templates that work in both
standalone landing container and main app contexts.
"""
import re
from pathlib import Path
from django.conf import settings
from django.urls import reverse, NoReverseMatch


def _get_api_path_by_name(url_name):
    """
    Extract URL path from api/urls.py by reading the file as plain text.

    Returns the path pattern (e.g., 'docs/') for a given name (e.g., 'swagger-ui').
    This reads the file directly without importing, avoiding Django model dependency issues.
    """
    try:
        # Read api/urls.py as plain text - no imports needed!
        api_urls_file = Path(__file__).parent.parent / 'api' / 'urls.py'

        if not api_urls_file.exists():
            return None

        content = api_urls_file.read_text()

        # Parse path patterns using regex, matching complete path() calls
        # Match: path("PATH", ...), ensuring we don't span multiple path() calls
        # Strategy: Find name="TARGET" first, then look backwards for the nearest path("...")

        # Find the position of name="url_name"
        name_pattern = rf'name\s*=\s*["\']({re.escape(url_name)})["\']'
        name_match = re.search(name_pattern, content)

        if not name_match:
            return None

        # Look backwards from the name to find the nearest path("...") declaration
        # Search in the substring before the name match
        content_before = content[:name_match.start()]

        # Find the last occurrence of path("PATH") before the name
        path_pattern = r'path\(\s*["\']([^"\']+)["\']\s*,'
        path_matches = list(re.finditer(path_pattern, content_before))

        if path_matches:
            # Get the last match (closest to our name parameter)
            last_path_match = path_matches[-1]
            return last_path_match.group(1)

    except (FileNotFoundError, PermissionError, Exception):
        # File not found or can't be read - return None to trigger fallback
        pass

    return None


def url_namespace(request):
    """
    Provide URL namespace prefix for landing URLs.

    In standalone landing container: '' (no namespace)
    In main app: 'landing:' (namespaced)

    Detection is based on ROOT_URLCONF setting.
    """
    # Check if we're in standalone landing container or main app
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'

    # Determine main_app_url for cross-container linking
    main_app_url = getattr(settings, 'MAIN_APP_URL', None)
    if not main_app_url or settings.DEBUG:
        scheme = 'https' if request.is_secure() else 'http'
        main_app_url = f"{scheme}://{request.get_host()}"

    # API documentation URLs
    if is_standalone:
        # Standalone landing container - read patterns from api/urls.py and construct
        swagger_path = _get_api_path_by_name('swagger-ui')
        redoc_path = _get_api_path_by_name('redoc')

        api_swagger_url = f"{main_app_url}/api/v1/{swagger_path}" if swagger_path else f"{main_app_url}/api/v1/docs/"
        api_redoc_url = f"{main_app_url}/api/v1/{redoc_path}" if redoc_path else f"{main_app_url}/api/v1/redoc/"
    else:
        # Main app - use Django reverse() for proper URL resolution
        try:
            api_swagger_url = reverse('api:swagger-ui')
            api_redoc_url = reverse('api:redoc')
        except NoReverseMatch:
            # Fallback: read from api/urls.py
            swagger_path = _get_api_path_by_name('swagger-ui')
            redoc_path = _get_api_path_by_name('redoc')
            api_swagger_url = f"{main_app_url}/api/v1/{swagger_path}" if swagger_path else f"{main_app_url}/api/v1/docs/"
            api_redoc_url = f"{main_app_url}/api/v1/{redoc_path}" if redoc_path else f"{main_app_url}/api/v1/redoc/"

    return {
        'landing_ns': '' if is_standalone else 'landing:',
        'main_app_url': main_app_url,
        'api_swagger_url': api_swagger_url,
        'api_redoc_url': api_redoc_url,
    }
