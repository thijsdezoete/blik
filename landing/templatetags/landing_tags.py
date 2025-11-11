"""
Custom template tags for landing app.

Provides namespace-aware URL reversal for templates that work in both
standalone landing container and main app contexts.

Also provides git-based metadata tags for AI search optimization:
- last_updated: Show "Last updated" dates from git
- article_schema: Generate Schema.org Article structured data
- page_author: Display author attribution
"""
from django import template
from django.conf import settings
from django.urls import reverse
from django.utils.safestring import mark_safe
import json
from ..git_metadata import get_template_metadata

register = template.Library()


@register.simple_tag
def landing_url(view_name):
    """
    Reverse a landing URL with appropriate namespace.

    In standalone landing container: reverse('index')
    In main app: reverse('landing:index')
    """
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'

    if is_standalone:
        return reverse(view_name)
    else:
        return reverse(f'landing:{view_name}')


@register.filter
def get_item(dictionary, key):
    """
    Template filter to get item from dict by key.

    Usage: {{ mydict|get_item:key }}
    Equivalent to: mydict[key] or mydict.get(key)
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


# =============================================================================
# Git-based Metadata Tags (for AI Search Optimization)
# =============================================================================

@register.simple_tag(takes_context=True)
def page_metadata(context, template_name=None):
    """
    Get git metadata for the current page.

    Usage in template:
        {% page_metadata as metadata %}
        {{ metadata.last_modified_iso }}
        {{ metadata.primary_author }}

    Args:
        template_name: Optional template name override

    Returns:
        dict with keys: last_modified, last_modified_iso, authors, primary_author, etc.
    """
    if template_name is None:
        # Try to get template name from context
        template_name = context.template_name if hasattr(context, 'template_name') else None

    if template_name:
        return get_template_metadata(template_name)

    # Fallback: empty metadata
    from ..git_metadata import _get_default_metadata
    return _get_default_metadata()


@register.simple_tag
def last_updated(template_name, format_string=None):
    """
    Display last updated date for a template from git history.

    Usage:
        {% last_updated "landing/dreyfus_model.html" %}
        {% last_updated "landing/index.html" format_string="%B %d, %Y" %}

    Args:
        template_name: Template path like "landing/dreyfus_model.html"
        format_string: Optional strftime format (default: "MMMM D, YYYY")

    Returns:
        Formatted date string
    """
    metadata = get_template_metadata(template_name)
    last_mod = metadata.get('last_modified')

    if not last_mod:
        return ""

    if format_string:
        return last_mod.strftime(format_string)

    # Default format: "January 15, 2025"
    return last_mod.strftime("%B %d, %Y")


@register.simple_tag
def page_author(template_name):
    """
    Get primary author for a template from git history.

    Usage:
        {% page_author "landing/dreyfus_model.html" %}

    Returns:
        Author name or empty string
    """
    metadata = get_template_metadata(template_name)
    return metadata.get('primary_author', '') or ''


@register.simple_tag
def article_schema(
    template_name,
    headline,
    description,
    canonical_url,
    author_name=None,
    image_url=None
):
    """
    Generate Schema.org Article structured data with git-based timestamps.

    Usage in template:
        {% article_schema "landing/dreyfus_model.html" headline="..." description="..." canonical_url="..." %}

    Args:
        template_name: Template path for git metadata
        headline: Article headline
        description: Article description
        canonical_url: Full canonical URL
        author_name: Optional author override (uses git by default)
        image_url: Optional featured image URL

    Returns:
        Safe HTML script tag with JSON-LD structured data
    """
    metadata = get_template_metadata(template_name)

    # Use git metadata for dates
    date_published = metadata.get('last_modified_iso', '2025-01-01T00:00:00Z')
    date_modified = metadata.get('last_modified_iso', date_published)

    # Use git author or fallback to organization
    if author_name is None:
        author_name = metadata.get('primary_author') or settings.SITE_NAME

    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "url": canonical_url,
        "datePublished": date_published,
        "dateModified": date_modified,
        "author": {
            "@type": "Person" if metadata.get('primary_author') else "Organization",
            "name": author_name
        },
        "publisher": {
            "@type": "Organization",
            "name": settings.SITE_NAME,
            "url": f"https://{settings.SITE_DOMAIN}"
        }
    }

    # Add image if provided
    if image_url:
        schema["image"] = {
            "@type": "ImageObject",
            "url": image_url,
            "width": "1200",
            "height": "630"
        }

    json_ld = json.dumps(schema, indent=2, ensure_ascii=False)
    return mark_safe(f'<script type="application/ld+json">\n{json_ld}\n</script>')


@register.simple_tag
def breadcrumb_schema(items):
    """
    Generate Schema.org BreadcrumbList structured data.

    Usage:
        {% breadcrumb_schema breadcrumbs %}

    Args:
        items: List of dicts with keys: name, url, position

    Returns:
        Safe HTML script tag with JSON-LD structured data
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": []
    }

    for item in items:
        schema["itemListElement"].append({
            "@type": "ListItem",
            "position": item.get('position', 1),
            "name": item.get('name', ''),
            "item": item.get('url', '')
        })

    json_ld = json.dumps(schema, indent=2, ensure_ascii=False)
    return mark_safe(f'<script type="application/ld+json">\n{json_ld}\n</script>')


@register.simple_tag
def faq_schema(questions_and_answers):
    """
    Generate Schema.org FAQPage structured data.

    Usage:
        {% faq_schema faqs %}

    Args:
        questions_and_answers: List of dicts with keys: question, answer

    Returns:
        Safe HTML script tag with JSON-LD structured data
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": []
    }

    for qa in questions_and_answers:
        schema["mainEntity"].append({
            "@type": "Question",
            "name": qa.get('question', ''),
            "acceptedAnswer": {
                "@type": "Answer",
                "text": qa.get('answer', '')
            }
        })

    json_ld = json.dumps(schema, indent=2, ensure_ascii=False)
    return mark_safe(f'<script type="application/ld+json">\n{json_ld}\n</script>')


@register.simple_tag
def software_app_schema(name, description, url, price=None, currency="USD"):
    """
    Generate Schema.org SoftwareApplication structured data.

    Usage:
        {% software_app_schema "Blik" "360 feedback" "https://blik360.com" price=0 %}

    Returns:
        Safe HTML script tag with JSON-LD structured data
    """
    schema = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": name,
        "description": description,
        "url": url,
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "Any (Web-based)",
        "offers": {
            "@type": "Offer",
            "price": str(price) if price is not None else "0",
            "priceCurrency": currency
        }
    }

    json_ld = json.dumps(schema, indent=2, ensure_ascii=False)
    return mark_safe(f'<script type="application/ld+json">\n{json_ld}\n</script>')
