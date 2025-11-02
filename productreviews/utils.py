"""
Utility functions for product reviews.
"""
from django.db.models import Avg, Count, Q
from .models import ProductReview


def get_aggregate_rating_data():
    """
    Get aggregate rating data for all approved, published product reviews.
    Returns data formatted for JSON-LD structured data.

    Returns:
        dict: Contains aggregateRating and individual reviews for JSON-LD,
              or None if insufficient reviews exist.
    """
    # Get all approved and published reviews
    reviews = ProductReview.objects.filter(
        status='approved',
        is_active=True,
        published_date__isnull=False
    ).order_by('-published_date')

    # Calculate aggregate stats
    stats = reviews.aggregate(
        avg_rating=Avg('rating'),
        total_count=Count('id')
    )

    review_count = stats['total_count'] or 0
    avg_rating = stats['avg_rating']

    # Only return data if we have at least 1 review
    if review_count < 1 or avg_rating is None:
        return None

    # Format aggregate rating for JSON-LD
    aggregate_rating = {
        'ratingValue': f"{avg_rating:.1f}",
        'ratingCount': str(review_count),
        'bestRating': '5',
        'worstRating': '1'
    }

    # Get individual reviews (limit to most recent 10 for JSON-LD)
    individual_reviews = []
    for review in reviews[:10]:
        review_data = {
            'author': {
                'name': review.reviewer_name,
            },
            'datePublished': review.published_date.isoformat(),
            'reviewBody': review.review_text,
            'name': review.review_title,
            'reviewRating': {
                'ratingValue': str(review.rating),
                'bestRating': '5',
                'worstRating': '1'
            }
        }

        # Add organization if available
        if review.reviewer_company:
            review_data['author']['organization'] = review.reviewer_company

        individual_reviews.append(review_data)

    return {
        'aggregateRating': aggregate_rating,
        'reviews': individual_reviews,
        'review_count': review_count,
        'avg_rating': avg_rating
    }


def get_featured_reviews(limit=3):
    """
    Get featured reviews for display on landing pages.

    Args:
        limit (int): Maximum number of reviews to return

    Returns:
        QuerySet: Featured, approved reviews
    """
    return ProductReview.objects.filter(
        status='approved',
        is_active=True,
        featured=True,
        published_date__isnull=False
    ).order_by('-published_date')[:limit]
