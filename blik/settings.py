"""
Django settings for blik project.
"""

from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environment variables
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    SESSION_COOKIE_SECURE=(bool, True),
    CSRF_COOKIE_SECURE=(bool, True),
)

# Read .env file if it exists
environ.Env.read_env(BASE_DIR / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-)32-g7%2_@jy@ycdh1lh2*)2pg8y$ftwd88j*vuc%ev%%t(@-f')

# Encryption key for sensitive data (SMTP passwords, etc.)
DEFAULT_ENCRYPTION_KEY = 'si1qWsaNKwavcargvESNiAZVdNmFt-ZieXiaziK-xnA='
ENCRYPTION_KEY = env('ENCRYPTION_KEY', default=DEFAULT_ENCRYPTION_KEY)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

# Warn if using default encryption key in production
if not DEBUG and ENCRYPTION_KEY == DEFAULT_ENCRYPTION_KEY:
    import sys
    print("\n" + "="*80, file=sys.stderr)
    print("⚠️  SECURITY WARNING: Using default ENCRYPTION_KEY in production!", file=sys.stderr)
    print("="*80, file=sys.stderr)
    print("Generate a new key with:", file=sys.stderr)
    print("  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"", file=sys.stderr)
    print("Then set ENCRYPTION_KEY in your environment variables.", file=sys.stderr)
    print("="*80 + "\n", file=sys.stderr)

ALLOWED_HOSTS = env('ALLOWED_HOSTS')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'csp',
    'axes',
    # Blik apps
    'core',
    'accounts',
    'questionnaires',
    'reviews',
    'reports',
    'notifications',
    'landing',
    'subscriptions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'csp.middleware.CSPMiddleware',
    'core.middleware.SetupMiddleware',
    'core.middleware.OrganizationMiddleware',
]

ROOT_URLCONF = 'blik.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'landing.context_processors.url_namespace',
            ],
        },
    },
]

WSGI_APPLICATION = 'blik.wsgi.application'

# Database
# Support DATABASE_URL for platforms like Dokploy, Railway, Heroku
# Format: postgres://user:password@host:port/dbname
import dj_database_url

# Use DATABASE_URL if set, otherwise build from individual vars
if env('DATABASE_URL', default=None):
    DATABASES = {
        'default': dj_database_url.config(
            default=env('DATABASE_URL'),
            conn_max_age=600
        )
    }
else:
    DATABASES = {
        'default': dj_database_url.config(
            default=f"postgres://{env('DATABASE_USER', default='blik')}:{env('DATABASE_PASSWORD', default='changeme')}@{env('DATABASE_HOST', default='localhost')}:{env('DATABASE_PORT', default='5432')}/{env('DATABASE_NAME', default='blik')}",
            conn_max_age=600
        )
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Authentication settings
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Whitenoise configuration for serving static files
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'mediafiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email configuration
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='localhost')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@example.com')

# Security settings
SESSION_COOKIE_SECURE = env('SESSION_COOKIE_SECURE')
CSRF_COOKIE_SECURE = env('CSRF_COOKIE_SECURE')
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# SSL is handled at the edge (reverse proxy/load balancer)
# DO NOT redirect to HTTPS at Django level - it will create infinite loops
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS (HTTP Strict Transport Security)
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0  # 1 year in production
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Referrer policy
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Content Security Policy (django-csp 4.0+ format)
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': ("'self'",),
        'script-src': ("'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "js.stripe.com"),
        'style-src': ("'self'", "'unsafe-inline'"),
        'img-src': ("'self'", "data:", "https:"),
        'font-src': ("'self'",),
        'connect-src': ("'self'", "*.stripe.com"),
        'frame-src': ("*.stripe.com",),
        'frame-ancestors': ("'none'",),
    }
}

# Django Axes - Account Lockout
AXES_FAILURE_LIMIT = 5  # Lock after 5 failed attempts
AXES_COOLOFF_TIME = 1  # Hours
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]  # Lock by combination
AXES_RESET_ON_SUCCESS = True
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',  # AxesStandaloneBackend should be first
    'django.contrib.auth.backends.ModelBackend',
]

# Organization settings
ORGANIZATION_NAME = env('ORGANIZATION_NAME', default='Blik')

# SEO settings
SITE_NAME = 'Blik360'
SITE_DOMAIN = env('SITE_DOMAIN', default='blik360.com')
SITE_PROTOCOL = env('SITE_PROTOCOL', default='https')
SITE_DESCRIPTION = 'Open source 360-degree feedback and performance review platform. Anonymous, secure, and easy to deploy.'
SITE_KEYWORDS = '360 feedback, performance review, peer review, employee feedback, open source, self-hosted'

# Stripe settings
STRIPE_PUBLISHABLE_KEY = env('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')
STRIPE_PRICE_ID_SAAS = env('STRIPE_PRICE_ID_SAAS', default='')
STRIPE_PRICE_ID_ENTERPRISE = env('STRIPE_PRICE_ID_ENTERPRISE', default='')

# CORS settings - allow landing page to call main app API
# Default to deriving from ALLOWED_HOSTS with site protocol
_cors_origins = env.list('CORS_ALLOWED_ORIGINS', default=None)
if _cors_origins is None:
    # Build from ALLOWED_HOSTS automatically
    CORS_ALLOWED_ORIGINS = [f'{SITE_PROTOCOL}://{host}' for host in ALLOWED_HOSTS if host != '*']
else:
    CORS_ALLOWED_ORIGINS = _cors_origins
CORS_ALLOW_CREDENTIALS = False

# Main app URL - used by landing app to make API calls
MAIN_APP_URL = env('MAIN_APP_URL', default=f'{SITE_PROTOCOL}://app.{SITE_DOMAIN}')

# Logging configuration - ensures logs go to stdout for gunicorn
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
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
            'level': env('DJANGO_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
        'subscriptions': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
