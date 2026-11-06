import sys
from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me-0123456789abcdef0123456789")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
# Public base URL of this backend, used for courier/payment callbacks.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "apps.customers",
    "apps.catalog",
    "apps.delivery",
    "apps.orders",
    "apps.payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "customers.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

LOGIN_URL = "staff:login"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 30,
    "DEFAULT_THROTTLE_RATES": {"otp": "5/hour"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=60),
    "ROTATE_REFRESH_TOKENS": True,
}

SPECTACULAR_SETTINGS = {"TITLE": "Pet24 API", "VERSION": "1.0.0"}

CACHES = {
    "default": env.cache("CACHE_URL", default="locmemcache://"),
}

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
TESTING = "test" in sys.argv[1:2]
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG or TESTING)
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "stock-sync": {"task": "apps.catalog.tasks.sync_stock", "schedule": 300},
    "branches-sync": {"task": "apps.catalog.tasks.sync_branches", "schedule": crontab(minute=7)},
    "expire-unpaid-orders": {"task": "apps.orders.tasks.expire_unpaid_orders", "schedule": 60},
    "refresh-shipments": {"task": "apps.delivery.tasks.refresh_active_shipments", "schedule": 120},
}

# --- stockapi (products, prices, stock) ---
STOCKAPI_URL = env("STOCKAPI_URL", default="").rstrip("/")
STOCKAPI_KEY = env("STOCKAPI_KEY", default="")
STOCKAPI_TIMEOUT = env.int("STOCKAPI_TIMEOUT", default=30)

# --- Orders ---
# Unpaid order is cancelled (and reservation released) after this many minutes.
ORDER_PAYMENT_TIMEOUT_MIN = env.int("ORDER_PAYMENT_TIMEOUT_MIN", default=20)
# After the receipt is printed at the branch till, the sale reaches stockapi with a lag.
# Reservation is kept this long after "assembled" so stock is not counted twice / not oversold.
SALES_SYNC_LAG_MIN = env.int("SALES_SYNC_LAG_MIN", default=30)

# --- Courier ---
COURIER_PROVIDER = env("COURIER_PROVIDER", default="manual")  # manual | yandex
YANDEX_DELIVERY_TOKEN = env("YANDEX_DELIVERY_TOKEN", default="")
YANDEX_DELIVERY_URL = env("YANDEX_DELIVERY_URL", default="https://b2b.taxi.yandex.net")
YANDEX_TAXI_CLASS = env("YANDEX_TAXI_CLASS", default="courier")
COURIER_SEARCH_TIMEOUT_MIN = env.int("COURIER_SEARCH_TIMEOUT_MIN", default=20)

# --- Payments ---
PAYME_MERCHANT_ID = env("PAYME_MERCHANT_ID", default="")
PAYME_KEY = env("PAYME_KEY", default="")
PAYME_CHECKOUT_URL = env("PAYME_CHECKOUT_URL", default="https://checkout.paycom.uz")
CLICK_SERVICE_ID = env("CLICK_SERVICE_ID", default="")
CLICK_MERCHANT_ID = env("CLICK_MERCHANT_ID", default="")
CLICK_SECRET_KEY = env("CLICK_SECRET_KEY", default="")
PAYMENT_RETURN_URL = env("PAYMENT_RETURN_URL", default="pet24://payment-return")

# --- SMS / OTP ---
SMS_BACKEND = env("SMS_BACKEND", default="console")  # console | eskiz
ESKIZ_EMAIL = env("ESKIZ_EMAIL", default="")
ESKIZ_PASSWORD = env("ESKIZ_PASSWORD", default="")
ESKIZ_FROM = env("ESKIZ_FROM", default="4546")
OTP_TEXT = env("OTP_TEXT", default="Pet24: kod podtverzhdeniya {code}")
OTP_TTL_SEC = 300
OTP_RESEND_SEC = 60
OTP_MAX_ATTEMPTS = 5

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
