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
