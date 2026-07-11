import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from tuckit.env import env, env_bool, env_list, parse_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = env_bool("DJANGO_DEBUG", default=False)

if DEBUG:
    SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
    ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
else:
    SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
    ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required when DEBUG is False")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tuckit.core",
    "tuckit.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:home"
LOGOUT_REDIRECT_URL = "web:login"

ROOT_URLCONF = "tuckit.urls"
WSGI_APPLICATION = "tuckit.wsgi.application"

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
                "tuckit.web.context_processors.sidebar_areas",
                "tuckit.web.context_processors.inbox_count",
                "tuckit.web.context_processors.switchable_workspaces",
            ],
        },
    },
]

DATABASES = {"default": parse_database_url(env("DATABASE_URL", required=True))}
_db = DATABASES["default"]
if _db["ENGINE"].endswith("sqlite3") and _db["NAME"] != ":memory:" and not os.path.isabs(_db["NAME"]):
    _db["NAME"] = str(BASE_DIR / _db["NAME"])

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Self-service registration is OFF by default (self-host provisions via CLI).
# Cloud flips this on. See docs/superpowers/specs/2026-07-11-auth-org-model-design.md.
REGISTRATION_OPEN = env_bool("TUCKIT_REGISTRATION_OPEN", default=False)
# Dotted path to a callable run right after signup, as hook(user=, org=).
# Core ships None (no-op); cloud sets it to attach billing. Never in core.
TUCKIT_SIGNUP_HOOK = env("TUCKIT_SIGNUP_HOOK", default=None) or None

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Manifest storage requires collectstatic to have built the manifest — true in
# production, not in dev/tests. Gate on DEBUG: plain storage in dev/test (so
# {% static %} needs no manifest), WhiteNoise compressed-manifest in production.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

# Korean UI: makes django's timesince/date filters render in Korean
# ("2시간 전"), not the default English ("2 hours, 38 minutes").
LANGUAGE_CODE = "ko-kr"
USE_I18N = True

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "DEBUG" if DEBUG else "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
