"""
Единый модуль настроек. Всё, что отличается между окружениями, приходит из переменных
окружения (см. .env.example в корне репозитория), поэтому отдельные dev/prod-модули не нужны.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, ["https://localhost", "http://localhost:5173"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
    LDAP_ENABLED=(bool, False),
)
# .env читает docker compose (env_file); локальные тесты работают на значениях по умолчанию

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# TLS терминируется на Caddy; Django доверяет его заголовку
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Cookie сессии (админка) и CSRF — только по HTTPS; в отладке без TLS — обычные
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 8 * 3600
X_FRAME_OPTIONS = "DENY"
# HSTS и перенаправление HTTP → HTTPS делает Caddy для всех ответов (infra/caddy/Caddyfile)
SILENCED_SYSTEM_CHECKS = ["security.W004", "security.W008"]
USE_X_FORWARDED_HOST = True

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
    "treebeard",
    "auditlog",
    "django_celery_beat",
    "rest_framework_simplejwt.token_blacklist",
    "django_prometheus",
    "channels",
]
# Порядок отражает зависимости модулей: нижние слои раньше верхних
LOCAL_APPS = [
    "apps.core",
    "apps.topology",
    "apps.accounts",
    "apps.audit",
    "apps.normalization",
    "apps.assets",
    "apps.telemetry",
    "apps.ingestion",
    "apps.integrations",
    "apps.forecasting",
    "apps.incidents",
    "apps.workorders",
    "apps.notifications",
    "apps.analytics",
    "apps.training",
    "apps.wiki",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
    "apps.audit.middleware.ActionLogMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

# PostgreSQL + TimescaleDB в контейнере; SQLite — только для быстрых локальных тестов
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["ENGINE"] = "django_prometheus.db.backends.postgresql"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]
# Первым — блокировка после серии неудачных входов (apps/accounts/lockout.py)
AUTHENTICATION_BACKENDS = [
    "apps.accounts.lockout.LockoutBackend",
    "django.contrib.auth.backends.ModelBackend",
]
LOCKOUT_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# LDAP/AD: реальный контроллер домена недоступен, поэтому в compose поднимается
# тестовый LDAP-сервер. Бэкенд подключается только если включён флагом.
if env("LDAP_ENABLED"):
    from apps.accounts.ldap import configure_ldap

    AUTHENTICATION_BACKENDS.insert(1, "django_auth_ldap.backend.LDAPBackend")
    configure_ldap(env, globals())

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Каталог с сырыми данными заказчика (монтируется read-only) и артефакты моделей
DATA_DIR = Path(env("DATA_DIR", default=str(BASE_DIR.parent / "data")))
ARTIFACTS_DIR = Path(env("ARTIFACTS_DIR", default=str(BASE_DIR.parent / "artifacts")))

# Контур: combat — работа на данных заказчика; training — учебный полигон со своей базой, темой Kafka
# и help desk. Один и тот же образ; контур меняет только окружение, поэтому учебный не может задеть боевой.
CONTOUR = env("CONTOUR", default="combat")
CONTOUR_URLS = {
    "combat": env("COMBAT_URL", default="https://localhost"),
    "training": env("TRAINING_URL", default="https://localhost:8443"),
    "simulator": env("SIMULATOR_URL", default="http://localhost:8095"),
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["apps.core.permissions.RoleModelPermissions"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.DefaultPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # JSON — основной обмен; XML — по требованию ТЗ §7 (Accept: application/xml или ?format=xml)
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework_xml.renderers.XMLRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework_xml.parsers.XMLParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}
# Короткий access (утечка токена живёт недолго), интерфейс обновляет его сам по refresh.
# Refresh ротируется при каждом обновлении, старый попадает в чёрный список; выход отзывает текущий.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Collector Incident Forecast API",
    "DESCRIPTION": "Прогнозирование отказов датчиков и инцидентов в инженерных коллекторах",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # схема и Swagger — только после входа (в браузере — через сессию админки)
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "COMPONENT_SPLIT_REQUEST": True,
}

CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_SEND_TASK_EVENTS = True  # нужно celery-exporter для метрик
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# Импорт истории идёт десятки минут: одна задача на воркер за раз, и Redis не должен
# переотдавать «зависшую» задачу другому воркеру до её завершения (по умолчанию — через час)
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 12 * 3600}

KAFKA = {
    "BOOTSTRAP_SERVERS": env("KAFKA_BOOTSTRAP_SERVERS", default="localhost:9092"),
    "TOPIC_RAW_EVENTS": env("KAFKA_TOPIC_RAW_EVENTS", default="smvu.raw-events"),
    "CONSUMER_GROUP": env("KAFKA_CONSUMER_GROUP", default="collector-forecast"),
    # Команды симулятору (учебный контур): единственный канал в полевой контур — тот же брокер
    "TOPIC_SIM_COMMANDS": env("KAFKA_TOPIC_SIM_COMMANDS", default="sim.training-commands"),
}

INTEGRATIONS = {
    "HELPDESK_URL": env("HELPDESK_URL", default="http://mock-helpdesk:8080"),
    "WEATHER_URL": env("WEATHER_URL", default="https://archive-api.open-meteo.com/v1/archive"),
}

AUDITLOG_INCLUDE_ALL_MODELS = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
