"""
Django settings for FlockTrade project.
AI-Powered Forex Trading Platform
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-change-me-in-production-xk3j2h1g5f4d6s7a8p9q0w",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,flocktrade.server-365.com"
).split(",")

# Application definition
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    "django_filters",
    # Local apps
    "accounts",
    "trading",
    "ai",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "flocktrade.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "flocktrade.wsgi.application"
ASGI_APPLICATION = "flocktrade.asgi.application"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "flocktrade"),
        "USER": os.environ.get("DB_USER", "trader"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "ft_db_s3cur3_2026"),
        "HOST": os.environ.get("DB_HOST", "flocktrade-db-b4tnfq"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# Redis / Channels
REDIS_URL = os.environ.get("REDIS_URL", "redis://flocktrade-redis-7kna89:6379")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# WhiteNoise for SPA serving
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Frontend SPA directory (built React app)
FRONTEND_DIR = BASE_DIR / "spa"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "100/minute",
        "login": "5/minute",
        "login_user": "10/minute",
    },
}

# JWT Settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.environ.get("JWT_ACCESS_LIFETIME_MINUTES", 15))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.environ.get("JWT_REFRESH_LIFETIME_DAYS", 7))
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# CORS
CORS_ALLOWED_ORIGINS = os.environ.get(
    "DJANGO_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",")
CORS_ALLOW_CREDENTIALS = True

# Security (production)
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULE = {
    "scanner-every-minute": {
        "task": "trading.tasks.run_scanner",
        "schedule": 60.0,
    },
    "exit-monitor-every-minute": {
        "task": "trading.tasks.monitor_exits",
        "schedule": 60.0,
    },
    "mt5-health-check": {
        "task": "trading.tasks.health_check",
        "schedule": 30.0,
    },
}

# FlockTrade Trading Config
MT5_HOST = os.environ.get("MT5_HOST", "mt5-trading")
MT5_PORT = int(os.environ.get("MT5_PORT", 8001))
MT5_ACCOUNT = os.environ.get("MT5_ACCOUNT", "")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")

SYMBOLS = os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT,XRPUSDT").split(",")
LOT_SIZE_FOREX = float(os.environ.get("LOT_SIZE_FOREX", 1.0))
LOT_SIZE_GOLD = float(os.environ.get("LOT_SIZE_GOLD", 0.1))
TP_PIPS_FOREX = int(os.environ.get("TP_PIPS_FOREX", 2))
SL_PIPS_FOREX = int(os.environ.get("SL_PIPS_FOREX", 5))
TP_PIPS_GOLD = int(os.environ.get("TP_PIPS_GOLD", 20))
SL_PIPS_GOLD = int(os.environ.get("SL_PIPS_GOLD", 50))
MAX_DAILY_LOSSES = int(os.environ.get("MAX_DAILY_LOSSES", 3))
MAX_DAILY_LOSS_USD = float(os.environ.get("MAX_DAILY_LOSS_USD", 100))

# Session hours (server time)
ASIA_START = int(os.environ.get("ASIA_START", 1))
ASIA_END = int(os.environ.get("ASIA_END", 6))
LONDON_START = int(os.environ.get("LONDON_START", 8))
LONDON_END = int(os.environ.get("LONDON_END", 12))
NY_START = int(os.environ.get("NY_START", 13))
NY_END = int(os.environ.get("NY_END", 20))

# AI Config
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SCOUT_MODEL = os.environ.get("SCOUT_MODEL", "anthropic/claude-haiku-4.5")
CONFIRMER_MODEL = os.environ.get("CONFIRMER_MODEL", "anthropic/claude-sonnet-4-6")
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", 15))

# Binance Config
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BINANCE_TESTNET_API_KEY = os.environ.get("BINANCE_TESTNET_API_KEY", "KQKTVnKQPMQO8p5gPBrxTPGBhFU3RHkqscLcaM1x1s8V1rhsrjNymXTNTVwS3q4N")
BINANCE_TESTNET_API_SECRET = os.environ.get("BINANCE_TESTNET_API_SECRET", "1gHyYaEKZwvHguaNlYuiJxDmSdmDAgAY4yi3Zg7gqurxAO66NLqEweK1gK8r1DUc")
EXCHANGE = os.environ.get("EXCHANGE", "binance")

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "trading": {"level": "DEBUG", "propagate": True},
        "ai": {"level": "DEBUG", "propagate": True},
        "accounts": {"level": "INFO", "propagate": True},
    },
}
