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
    'apps.emails',
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
FREE_SHIPPING_THRESHOLD_NOK = env.int('FREE_SHIPPING_THRESHOLD_NOK', default=299)

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
# Canonical URL is the bare apex — no `www` — and `.env` on every environment
# must match. Hardcoding the domain anywhere outside this setting is a bug.
STOREFRONT_URL = env('STOREFRONT_URL', default='https://sjokoloco.no')

# Welcome / "glemt passord" links are valid for 7 days — customers often sign
# up at a stand and read their mail days later.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 7

# Ordering paused: the catalogue stays browsable but no order may be created.
# The storefront hides every buy control (NEXT_PUBLIC_ORDERING_PAUSED); this is
# the hard stop, so a stale tab, a saved cart or a direct API call cannot slip
# an order through while production is down.
ORDERING_PAUSED = env.bool('ORDERING_PAUSED', default=False)

# The 20% code the loyalty welcome e-mail hands out, and the one the checkout
# applies automatically for a signed-in customer. Kept configurable so the
# offer can be swapped or retired from the admin without a deploy: if the
# coupon is missing or inactive, the storefront simply stops advertising it.
LOYALTY_DISCOUNT_CODE = env('LOYALTY_DISCOUNT_CODE', default='STAND')

# ── Profrakt (EDI) — shipping labels ─────────────────────────────────────
# The storefront still quotes prices at checkout (POST /costs/v2, which creates
# nothing). These credentials are for POST /consignments, called only when ops
# ships the order, so the carrier never announces a parcel that does not exist.
PROFRAKT_BASE = env('PROFRAKT_BASE', default='https://edi.no')
PROFRAKT_KEY = env('PROFRAKT_KEY', default='')
PROFRAKT_SENDER = env('PROFRAKT_SENDER', default='')
PROFRAKT_TRANSPORT_AGREEMENT = env('PROFRAKT_TRANSPORT_AGREEMENT', default='')
PROFRAKT_POSTNORD_AGREEMENT = env('PROFRAKT_POSTNORD_AGREEMENT', default='')
PROFRAKT_HTTP_TIMEOUT = env.float('PROFRAKT_HTTP_TIMEOUT', default=20.0)

# Admin dashboard base used in internal notification emails ("see order in admin").
ADMIN_URL = env('ADMIN_URL', default='https://admin.sjokoloco.no')

# Recipients for internal "new signup / new order" notification emails.
# Comma-separated list (e.g. "terje@sjokoloco.no,andreas@sjokoloco.no").
# All listed addresses get bcc-style copies of #2 + #4 in one SMTP send.
ADMIN_NOTIFY_EMAILS = env.list('ADMIN_NOTIFY_EMAILS', default=[])

# Who hears about a WhatsApp-link outage. Deliberately NOT ADMIN_NOTIFY_EMAILS:
# that list also receives every customer order e-mail (apps/emails/orders.py),
# so adding a developer there to get outage alerts would silently CC them on
# the shop's order flow. Defaults to ADMIN_NOTIFY_EMAILS, so this changes
# nothing until WHATSAPP_ALERT_EMAILS is actually set in the environment.
WHATSAPP_ALERT_EMAILS = env.list('WHATSAPP_ALERT_EMAILS', default=ADMIN_NOTIFY_EMAILS)

# ── Storefront cache busting ────────────────────────────────────────────
# The Next.js shop caches product pages for 60s (stale-while-revalidate), so
# an edit is not visible on the next refresh — which reads as "the toggle did
# nothing". Saving a product pings the storefront to drop those pages.
# Best-effort: a failure here never blocks the save.
# Deliberately NOT STOREFRONT_URL: that one is the public canonical URL used
# in e-mail links, and this call should go straight to the Next.js process on
# localhost — no DNS, no TLS, no nginx hop.
REVALIDATE_URL = env('REVALIDATE_URL', default='http://127.0.0.1:3000')
REVALIDATE_SECRET = env('REVALIDATE_SECRET', default='')
REVALIDATE_TIMEOUT_SECONDS = env.float('REVALIDATE_TIMEOUT_SECONDS', default=3.0)

# ── WhatsApp ops alerts (WAHA) ──────────────────────────────────────────
# A short "new order" ping to the shop owner's phone, sent from the same
# place as the ops e-mail above. WAHA is a Docker container on this host
# bound to 127.0.0.1, holding a linked-device session for the shop's number,
# so nothing leaves the machine and there is no WhatsApp Business account.
#
# Off unless WHATSAPP_ENABLED is set: shipping this code changes nothing
# until the phone is linked and the flag is turned on.
WHATSAPP_ENABLED = env.bool('WHATSAPP_ENABLED', default=False)
WAHA_BASE_URL = env('WAHA_BASE_URL', default='http://127.0.0.1:3004')
WAHA_API_KEY = env('WAHA_API_KEY', default='')
WAHA_SESSION = env('WAHA_SESSION', default='sjokoloko')
# Recipient, in WhatsApp's JID form: "<country><number>@c.us".
WHATSAPP_ADMIN_CHAT_ID = env('WHATSAPP_ADMIN_CHAT_ID', default='')
# Kept short — this call sits inside the Vipps webhook.
WAHA_TIMEOUT_SECONDS = env.float('WAHA_TIMEOUT_SECONDS', default=5.0)

# When set, every transactional email is rewritten to this address and the
# original recipient is stamped into the subject. Leave empty in production.
EMAIL_TEST_OVERRIDE = env('EMAIL_TEST_OVERRIDE', default='')

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
        'apps.emails': {
            'handlers': ['console'],
            'level': env('EMAIL_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
    },
}
