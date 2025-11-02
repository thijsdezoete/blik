"""
Utility to fetch product review data from main app API.

The landing container runs separately without database access,
so it fetches review data via HTTP from the main app's API endpoint.
"""
import requests
from django.conf import settings


def get_review_data_from_api():
    """
    Fetch aggregate review data from the main app's API.

    Returns:
        dict: Review data with aggregateRating and reviews, or None if unavailable
    """
    # Determine API URL based on environment
    # In production with nginx, we can call the internal service directly
    # In development, we need to call via the external URL

    if hasattr(settings, 'MAIN_APP_URL'):
        api_url = f"{settings.MAIN_APP_URL}/api/reviews/aggregate"
    else:
        # Fallback: try to reach via Docker network (blik_default)
        # The web service is accessible as 'web' or 'blik-web-1' on the Docker network
        api_url = "http://web:8000/api/reviews/aggregate"

    try:
        response = requests.get(api_url, timeout=2)
        response.raise_for_status()
        data = response.json()

        if data.get('has_reviews'):
            return data
        return None
    except (requests.RequestException, ValueError, KeyError) as e:
        # Log the error but don't break the page
        print(f"Warning: Could not fetch review data from API: {e}")
        return None
