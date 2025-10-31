from django.http import HttpResponse
from django.conf import settings


def sitemap(request):
    """Generate XML sitemap for search engines."""
    # Detect actual protocol from request (handles Cloudflare/proxy SSL termination)
    # Django's request.is_secure() respects SECURE_PROXY_SSL_HEADER setting
    protocol = 'https' if request.is_secure() else 'http'

    # Fallback: production is always HTTPS when accessed via proper domain
    # (Development might be http://localhost)
    if protocol == 'http' and not ('localhost' in request.get_host() or '127.0.0.1' in request.get_host()):
        protocol = 'https'

    base_url = f"{protocol}://{settings.SITE_DOMAIN}"

    # Detect if we're in standalone landing container or main app
    is_standalone = getattr(settings, 'ROOT_URLCONF', '') == 'landing_urls'
    prefix = '' if is_standalone else '/landing'

    sitemap_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>{base_url}{prefix}/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/signup/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/hr-managers/</loc>
        <lastmod>2025-10-28</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/open-source/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/dreyfus-model/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/agency-levels/</loc>
        <lastmod>2025-10-31</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/eu-tech/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>{base_url}{prefix}/privacy/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
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
