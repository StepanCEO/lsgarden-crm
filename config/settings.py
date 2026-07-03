from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv_file(BASE_DIR / '.env')


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_list(name: str, default: str = '') -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(',') if item.strip()]


DEBUG = _env_bool('DJANGO_DEBUG', False)
CRM_AUTO_SEED_DEMO = _env_bool('CRM_AUTO_SEED_DEMO', False)
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-plantflow-crm-dev-secret'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY is required when DJANGO_DEBUG=0')

ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'crm',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'crm.middleware.RequestAuditMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'crm.middleware.AutoLogoutMiddleware',
    'crm.middleware.FraudDetectionMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'plant_crm'),
        'USER': os.getenv('POSTGRES_USER', 'plant_crm'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'plant_crm'),
        'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.getenv('POSTGRES_PORT', '5433'),
        'CONN_MAX_AGE': int(os.getenv('POSTGRES_CONN_MAX_AGE', '60')),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', True)
    SECURE_HSTS_PRELOAD = _env_bool('DJANGO_SECURE_HSTS_PRELOAD', True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_ENDPOINT_URL = os.getenv('AWS_S3_ENDPOINT_URL', '')
AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'ru-central1')
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_DEFAULT_ACL = 'public-read'
AWS_QUERYSTRING_AUTH = False
AWS_S3_FILE_OVERWRITE = False
AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}

if AWS_ACCESS_KEY_ID and AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {
                'access_key': AWS_ACCESS_KEY_ID,
                'secret_key': AWS_SECRET_ACCESS_KEY,
                'bucket_name': AWS_STORAGE_BUCKET_NAME,
                'endpoint_url': AWS_S3_ENDPOINT_URL,
                'region_name': AWS_S3_REGION_NAME,
                'signature_version': AWS_S3_SIGNATURE_VERSION,
                'default_acl': AWS_DEFAULT_ACL,
                'querystring_auth': AWS_QUERYSTRING_AUTH,
                'file_overwrite': AWS_S3_FILE_OVERWRITE,
            },
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }

MEDIA_URL = os.getenv('MEDIA_URL', f'https://{AWS_STORAGE_BUCKET_NAME}.storage.yandexcloud.net/') if AWS_STORAGE_BUCKET_NAME else '/media/'

# Avito email parser (IMAP)
AVITO_EMAIL_HOST = os.getenv('AVITO_EMAIL_HOST', '')
AVITO_EMAIL_PORT = int(os.getenv('AVITO_EMAIL_PORT', '993'))
AVITO_EMAIL_USER = os.getenv('AVITO_EMAIL_USER', '')
AVITO_EMAIL_PASSWORD = os.getenv('AVITO_EMAIL_PASSWORD', '')

# Avito Playwright (browser automation)
AVITO_USERNAME = os.getenv('AVITO_USERNAME', '')
AVITO_PASSWORD = os.getenv('AVITO_PASSWORD', '')
AVITO_AUTH_FILE = os.getenv('AVITO_AUTH_FILE', 'avito_auth.json')
AVITO_COOKIES_FILE = os.getenv('AVITO_COOKIES_FILE', 'avito_cookies.json')
AVITO_POLL_LIMIT = int(os.getenv('AVITO_POLL_LIMIT', '20'))

# Email (SMTP)
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.yandex.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '465'))
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', False)
EMAIL_USE_SSL = _env_bool('EMAIL_USE_SSL', not EMAIL_USE_TLS)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_OAUTH_TOKEN = os.getenv('EMAIL_OAUTH_TOKEN', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@crm.lsgarden.ru')

# Telegram
TG_INTEGRATION_MODE = os.getenv('TG_INTEGRATION_MODE', 'bot')
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '')
TG_GROUP_ID = os.getenv('TG_GROUP_ID', '')
TG_API_ID = os.getenv('TG_API_ID', '')
TG_API_HASH = os.getenv('TG_API_HASH', '')
TG_PHONE = os.getenv('TG_PHONE', '')
TG_SESSION_NAME = os.getenv('TG_SESSION_NAME', 'telegram_account')
TG_DIALOG_LIMIT = int(os.getenv('TG_DIALOG_LIMIT', '50'))
TG_HISTORY_LIMIT = int(os.getenv('TG_HISTORY_LIMIT', '40'))

# VK API
VK_API_TOKEN = os.getenv('VK_API_TOKEN', '')
VK_GROUP_ID = os.getenv('VK_GROUP_ID', '')

# Website forms webhook
SITE_WEBHOOK_TOKEN = os.getenv('SITE_WEBHOOK_TOKEN', '')
ONE_C_NOMENCLATURE_PATH = os.getenv('ONE_C_NOMENCLATURE_PATH', '')

# Shop (WooCommerce) admin sync (Playwright)
SHOP_ADMIN_URL = os.getenv('SHOP_ADMIN_URL', 'https://shop.lsgarden.ru')
SHOP_ADMIN_USERNAME = os.getenv('SHOP_ADMIN_USERNAME', '')
SHOP_ADMIN_PASSWORD = os.getenv('SHOP_ADMIN_PASSWORD', '')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'crm:login'
LOGIN_REDIRECT_URL = 'crm:dashboard'
LOGOUT_REDIRECT_URL = 'crm:login'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
    },
}
