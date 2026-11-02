import ipaddress

from django.conf import settings


def client_ip(request):
    """Return the visitor's IP address.

    Behind a proxy such as Cloudflare, REMOTE_ADDR is the proxy. When
    TRUSTED_CLIENT_IP_HEADER names a request.META key, use that header.
    The header is never read when the setting is empty, so it cannot be spoofed
    on installs without the proxy.
    """
    header = getattr(settings, "TRUSTED_CLIENT_IP_HEADER", "")
    if header:
        value = request.META.get(header, "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
    return request.META.get("REMOTE_ADDR", "")
