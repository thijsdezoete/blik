"""
Minimal Django settings for landing/marketing site container.

This configuration only includes what's needed to serve static landing pages.
No database, no authentication, no sessions - just templates and static files.
"""
from pathlib import Path
import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent

# Initialize environment variables
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)

# Read .env file if it exists
environ.Env.read_env(BASE_DIR / '.env')

# Security
SECRET_KEY = env('SECRET_KEY', default='landing-minimal-key-not-used-for-auth')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')

# Minimal application definition - only landing app
INSTALLED_APPS = [
    'django.contrib.staticfiles',  # For static file serving
    'django.contrib.contenttypes',  # Required by Django
    'django.contrib.sessions',  # For session management (assessment flow)
    'django.contrib.messages',  # For flash messages
    'landing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Serve static files
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',  # CSRF protection for forms
    'django.contrib.sessions.middleware.SessionMiddleware',  # Session support
    'django.contrib.messages.middleware.MessageMiddleware',  # Flash messages
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'landing_urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.static',
                'django.contrib.messages.context_processors.messages',
                'landing.context_processors.url_namespace',
                'landing.context_processors.organization_metadata',
            ],
        },
    },
]

WSGI_APPLICATION = 'landing_wsgi.application'

# Session configuration (using signed cookies - no database needed)
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

# Cache configuration (for other uses)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'landing-cache',
    }
}

# Message storage (for flash messages)
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# No database needed for static landing pages
DATABASES = {}

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Whitenoise for efficient static file serving with versioned manifest
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Security settings
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)  # Set to True in production with HTTPS
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)  # Set to True in production with HTTPS
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Trust proxy headers (Cloudflare/Traefik)
# This allows Django to detect HTTPS from X-Forwarded-Proto header
# Protocol is dynamically detected in templates via context processor
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# SEO settings
SITE_NAME = 'Blik360'
SITE_DOMAIN = env('SITE_DOMAIN', default='blik360.com')
# SITE_PROTOCOL: Only used for MAIN_APP_URL construction below
# Templates get protocol dynamically via context_processors.url_namespace()
SITE_PROTOCOL = env('SITE_PROTOCOL', default='http')
SITE_DESCRIPTION = 'Open source 360-degree feedback and performance review platform. Anonymous, secure, and easy to deploy.'
SITE_KEYWORDS = '360 feedback, performance review, open source, self-hosted, anonymous feedback, employee feedback'

# Stripe settings (optional for landing page)
STRIPE_PUBLISHABLE_KEY = env('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_PRICE_ID_SAAS = env('STRIPE_PRICE_ID_SAAS', default='')
STRIPE_PRICE_ID_ENTERPRISE = env('STRIPE_PRICE_ID_ENTERPRISE', default='')

# Main app URL - used by signup page to make API calls
MAIN_APP_URL = env('MAIN_APP_URL', default=f'{SITE_PROTOCOL}://app.{SITE_DOMAIN}')

# Growth hack configuration
# Organization is set by the API token - no need to configure separately
GROWTH_QUESTIONNAIRE_UUID = env('GROWTH_QUESTIONNAIRE_UUID', default='')
LANDING_SERVICE_API_TOKEN = env('LANDING_SERVICE_API_TOKEN', default='')

# Email configuration
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@blik360.com')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',  # This will log 500 errors with full traceback
            'propagate': False,
        },
    },
}
