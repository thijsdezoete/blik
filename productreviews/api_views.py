"""
API views for product reviews - used by landing pages to fetch review data.
"""
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from .utils import get_aggregate_rating_data


@require_GET
@cache_page(60 * 15)  # Cache for 15 minutes
def aggregate_reviews_api(request):
    """
    Public API endpoint that returns aggregate review data for JSON-LD.

    This is called by the landing pages (which run in a separate container)
    to get real-time review data for structured data / SEO.

    Returns:
        JSON response with aggregateRating and individual reviews,
        or empty object if no reviews exist.
    """
    rating_data = get_aggregate_rating_data()

    if not rating_data:
        return JsonResponse({
            'has_reviews': False,
            'aggregateRating': None,
            'reviews': []
        })

    return JsonResponse({
        'has_reviews': True,
        'aggregateRating': rating_data['aggregateRating'],
        'reviews': rating_data['reviews'],
        'review_count': rating_data['review_count'],
        'avg_rating': float(rating_data['avg_rating'])
    })
