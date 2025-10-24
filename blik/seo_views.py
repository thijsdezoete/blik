from django.http import HttpResponse
from django.conf import settings


def sitemap(request):
    """Generate XML sitemap for search engines."""
    base_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}"

    sitemap_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>{base_url}/landing/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>{base_url}/landing/open-source/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>{base_url}/landing/dreyfus-model/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>{base_url}/landing/eu-tech/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>{base_url}/landing/privacy/</loc>
        <lastmod>2025-10-24</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
</urlset>'''

    return HttpResponse(sitemap_xml, content_type='application/xml')


def robots(request):
    """Generate robots.txt for search engine crawlers."""
    base_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}"

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
