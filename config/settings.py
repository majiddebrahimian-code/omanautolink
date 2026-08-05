import mimetypes
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# Windows does not always register WebP in its MIME database.  Django's
# development media server should still return the right Content-Type, and
# production should mirror this mapping in its web server configuration.
mimetypes.add_type("image/webp", ".webp", strict=True)

SECRET_KEY = config("SECRET_KEY")

DEBUG = config("DEBUG", default=False, cast=bool)

# ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "rest_framework",
    # local apps
    "backoffice",
    "accounts",
    "cars",
    "core",
    "customers",
    "tracking",
    "blog",
    "integrations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.public_site",
                "core.admin_context.admin_shell",
                "backoffice.context_processors.panel_navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST", default="db"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# The canonical production domain belongs to deployment configuration, not the
# editable site settings table. Leave blank locally to use the current request.
PUBLIC_SITE_URL = config("PUBLIC_SITE_URL", default="")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CACHE_REDIS_URL = config(
    "CACHE_REDIS_URL",
    default="redis://redis:6379/1",
)

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_REDIS_URL,
    }
}

PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS = config(
    "PUBLIC_TRACKING_RATE_LIMIT_ATTEMPTS",
    default=10,
    cast=int,
)

PUBLIC_TRACKING_RATE_LIMIT_WINDOW_SECONDS = config(
    "PUBLIC_TRACKING_RATE_LIMIT_WINDOW_SECONDS",
    default=600,
    cast=int,
)
CELERY_BROKER_URL = config("REDIS_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = config("REDIS_URL", default="redis://redis:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Tehran"

# Telegram is deliberately disabled unless a deployment explicitly enables it.
# Keep the real token and webhook secret in .env only.
TELEGRAM_BOT_ENABLED = config("TELEGRAM_BOT_ENABLED", default=False, cast=bool)
TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_WEBHOOK_SECRET = config("TELEGRAM_WEBHOOK_SECRET", default="")
TELEGRAM_LINK_CODE_TTL_MINUTES = config(
    "TELEGRAM_LINK_CODE_TTL_MINUTES",
    default=15,
    cast=int,
)
TELEGRAM_CONFIRMATION_SESSION_TTL_MINUTES = config(
    "TELEGRAM_CONFIRMATION_SESSION_TTL_MINUTES",
    default=5,
    cast=int,
)
TELEGRAM_CUSTOMER_ACTIVATION_CODE_TTL_DAYS = config(
    "TELEGRAM_CUSTOMER_ACTIVATION_CODE_TTL_DAYS",
    default=30,
    cast=int,
)
TELEGRAM_TRACKING_RATE_LIMIT_ATTEMPTS = config(
    "TELEGRAM_TRACKING_RATE_LIMIT_ATTEMPTS",
    default=10,
    cast=int,
)
TELEGRAM_TRACKING_RATE_LIMIT_WINDOW_SECONDS = config(
    "TELEGRAM_TRACKING_RATE_LIMIT_WINDOW_SECONDS",
    default=600,
    cast=int,
)
TELEGRAM_OUTBOX_MAX_ATTEMPTS = config(
    "TELEGRAM_OUTBOX_MAX_ATTEMPTS",
    default=6,
    cast=int,
)
TELEGRAM_OUTBOX_SENDING_TIMEOUT_SECONDS = config(
    "TELEGRAM_OUTBOX_SENDING_TIMEOUT_SECONDS",
    default=300,
    cast=int,
)
TELEGRAM_HTTP_TIMEOUT_SECONDS = config(
    "TELEGRAM_HTTP_TIMEOUT_SECONDS",
    default=20,
    cast=int,
)
TELEGRAM_POLL_TIMEOUT_SECONDS = config(
    "TELEGRAM_POLL_TIMEOUT_SECONDS",
    default=30,
    cast=int,
)

# A durable outbox is the source of truth. Celery Beat periodically recovers
# retryable or stale messages even if a worker crashed after claiming one.
CELERY_BEAT_SCHEDULE = {
    "recover-due-telegram-outbox-messages": {
        "task": "integrations.process_due_telegram_outbox_messages",
        "schedule": 60.0,
    },
}
