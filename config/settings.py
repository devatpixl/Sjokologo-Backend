from pathlib import Path
from datetime import timedelta
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'apps.users',
    'apps.products',
    'apps.orders',
    'apps.utils',
    'apps.payments_vipps',
    'apps.coupons',
    'apps.bundles',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': env.db(),
}

AUTH_USER_MODEL = 'users.CustomUser'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
]

LANGUAGE_CODE = 'nb-no'
TIME_ZONE = 'Europe/Oslo'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Free shipping kicks in when the cart subtotal (NOK, before shipping) clears
# this threshold. Enforced in CreateOrderSerializer. Storefront mirrors this
# constant in lib/cart-shipping.ts — keep both in sync.
FREE_SHIPPING_THRESHOLD_NOK = env.int('FREE_SHIPPING_THRESHOLD_NOK', default=349)

# ── Email (Gmail SMTP) ─────────────────────────────────────────────
# Used for transactional mail like the loyalty signup confirmation.
# EMAIL_HOST_PASSWORD must be a Gmail "App password" (not the account
# password) — generated at https://myaccount.google.com/apppasswords.
EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env(
    'DEFAULT_FROM_EMAIL',
    default='Sjoko Loco <dev@pixlmedia.no>',
)

# Storefront base used inside transactional email links (e.g. "Handle her").
STOREFRONT_URL = env('STOREFRONT_URL', default='https://www.sjokoloco.no')

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ── Vipps ePayment ─────────────────────────────────────────────────────────
# All keys come from the Vipps developer portal. Keep them out of source
# control (use .env) — see .env.example for the full set.
VIPPS_BASE_URL = env('VIPPS_BASE_URL', default='https://apitest.vipps.no')
VIPPS_CLIENT_ID = env('VIPPS_CLIENT_ID', default='')
VIPPS_CLIENT_SECRET = env('VIPPS_CLIENT_SECRET', default='')
VIPPS_SUBSCRIPTION_KEY = env('VIPPS_SUBSCRIPTION_KEY', default='')
VIPPS_MERCHANT_SERIAL_NUMBER = env('VIPPS_MERCHANT_SERIAL_NUMBER', default='')
VIPPS_SYSTEM_NAME = env('VIPPS_SYSTEM_NAME', default='sjokoloko')
VIPPS_SYSTEM_VERSION = env('VIPPS_SYSTEM_VERSION', default='1.0.0')
VIPPS_SYSTEM_PLUGIN_NAME = env('VIPPS_SYSTEM_PLUGIN_NAME', default='sjokoloko-vipps')
VIPPS_SYSTEM_PLUGIN_VERSION = env('VIPPS_SYSTEM_PLUGIN_VERSION', default='1.0.0')
VIPPS_RETURN_URL_BASE = env(
    'VIPPS_RETURN_URL_BASE',
    default='http://localhost:3000/kasse/retur',
)
VIPPS_WEBHOOK_URL = env('VIPPS_WEBHOOK_URL', default='')
VIPPS_REFERENCE_PREFIX = env('VIPPS_REFERENCE_PREFIX', default='sl')
VIPPS_HTTP_TIMEOUT = env.float('VIPPS_HTTP_TIMEOUT', default=4.0)
VIPPS_TEST_PHONE = env('VIPPS_TEST_PHONE', default='')

# ── Vipps Login (OIDC) ──────────────────────────────────────────────────
VIPPS_LOGIN_ISSUER_URL = env(
    'VIPPS_LOGIN_ISSUER_URL',
    default='https://apitest.vipps.no/access-management-1.0/access',
)
VIPPS_LOGIN_USERINFO_URL = env(
    'VIPPS_LOGIN_USERINFO_URL',
    default='https://apitest.vipps.no/vipps-userinfo-api/userinfo/',
)
VIPPS_LOGIN_REDIRECT_URI = env(
    'VIPPS_LOGIN_REDIRECT_URI',
    default='http://localhost:8000/api/auth/vipps/callback/',
)
VIPPS_LOGIN_SCOPES = env(
    'VIPPS_LOGIN_SCOPES', default='openid name email phoneNumber'
)
VIPPS_LOGIN_STOREFRONT_FINISH_URL = env(
    'VIPPS_LOGIN_STOREFRONT_FINISH_URL',
    default='http://localhost:3000/vipps-finish',
)
VIPPS_LOGIN_HANDOFF_SECRET = env(
    'VIPPS_LOGIN_HANDOFF_SECRET', default=SECRET_KEY
)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'apps.payments_vipps': {
            'handlers': ['console'],
            'level': env('VIPPS_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
    },
}
