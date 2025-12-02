from django.http import HttpResponse
from django.conf import settings
import subprocess
from datetime import datetime


def get_template_lastmod(template_path):
    """Get last modification date from git for a template file."""
    try:
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%ci', '--', template_path],
            capture_output=True,
            text=True,
            cwd=settings.BASE_DIR
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse git date format: "2025-11-10 14:30:00 +0100"
            date_str = result.stdout.strip().split()[0]
            return date_str
    except Exception:
        pass
    return datetime.now().strftime('%Y-%m-%d')


def sitemap(request):
    """Generate XML sitemap dynamically from landing URL patterns."""
    from landing.urls import urlpatterns

    # Detect actual protocol from request (handles Cloudflare/proxy SSL termination)
    protocol = 'https' if request.is_secure() else 'http'
    if protocol == 'http' and not ('localhost' in request.get_host() or '127.0.0.1' in request.get_host()):
        protocol = 'https'

    base_url = f"{protocol}://{settings.SITE_DOMAIN}"
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'
    prefix = '' if is_standalone else '/landing'

    # URLs to exclude from sitemap (non-page endpoints)
    exclude_names = {
        'og_image', 'robots', 'sitemap',
        'dreyfus_assessment_submit', 'dreyfus_capture_email',
    }

    # Priority overrides (default is 0.8)
    priority_config = {
        'index': 1.0,
        'signup': 0.9,
        'hr_managers': 0.9,
        'developers': 0.9,
        'open_source': 0.9,
        'eu_tech': 0.9,
        'why_blik': 0.95,
        'dreyfus_assessment_start': 0.85,
        'privacy_policy': 0.5,
        'terms': 0.5,
        'about': 0.7,
        # vs-* pages get 0.9
        'vs_lattice': 0.9,
        'vs_culture_amp': 0.9,
        'vs_15five': 0.9,
        'vs_orangehrm': 0.9,
        'vs_odoo': 0.9,
        'vs_engagedly': 0.9,
        'vs_small_improvements': 0.9,
    }

    # Changefreq overrides (default is monthly)
    changefreq_config = {
        'index': 'weekly',
        'signup': 'weekly',
        'dreyfus_assessment_start': 'weekly',
        'privacy_policy': 'yearly',
        'terms': 'yearly',
    }

    urls = []
    for pattern in urlpatterns:
        name = getattr(pattern, 'name', None)
        if not name or name in exclude_names:
            continue

        # Get the URL path
        url_path = str(pattern.pattern)
        if url_path and not url_path.endswith('/'):
            continue  # Skip non-page URLs like og-image.png

        # Build template path to get lastmod from git
        template_path = f'templates/landing/{name}.html'

        lastmod = get_template_lastmod(template_path)
        priority = priority_config.get(name, 0.8)
        changefreq = changefreq_config.get(name, 'monthly')

        full_url = f"{base_url}{prefix}/{url_path}"

        urls.append(f'''    <url>
        <loc>{full_url}</loc>
        <lastmod>{lastmod}</lastmod>
        <changefreq>{changefreq}</changefreq>
        <priority>{priority}</priority>
    </url>''')

    sitemap_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>'''

    return HttpResponse(sitemap_xml, content_type='application/xml')


def robots(request):
    """Generate robots.txt for search engine crawlers."""
    # Detect actual protocol from request (handles Cloudflare/proxy SSL termination)
    # Django's request.is_secure() respects SECURE_PROXY_SSL_HEADER setting
    protocol = 'https' if request.is_secure() else 'http'

    # Fallback: production is always HTTPS when accessed via proper domain
    # (Development might be http://localhost)
    if protocol == 'http' and not ('localhost' in request.get_host() or '127.0.0.1' in request.get_host()):
        protocol = 'https'

    base_url = f"{protocol}://{settings.SITE_DOMAIN}"

    robots_txt = f'''User-agent: *
Allow: /
Disallow: /admin/
Disallow: /dashboard/
Disallow: /feedback/
Disallow: /reports/
Disallow: /setup/

Sitemap: {base_url}/sitemap.xml
'''

    return HttpResponse(robots_txt, content_type='text/plain')
