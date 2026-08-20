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
    "tuckit.web.middleware.TenantMiddleware",
    # Must follow TenantMiddleware: it reads request.org, which that one sets.
    "tuckit.web.middleware.LiveCursorMiddleware",
    # Anywhere below the tenant middleware: it only needs to see the exception,
    # not request.org. Kept next to it so the write-path middleware stay together.
    "tuckit.web.middleware.WritesBlockedMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:root"
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
                "tuckit.web.context_processors.switchable_orgs",
                "tuckit.web.context_processors.current_org",
                "tuckit.web.context_processors.auth_chrome",
                "tuckit.web.context_processors.onboarding",
                "tuckit.web.context_processors.capture_area",
                "tuckit.web.context_processors.live_cursor",
                "tuckit.web.context_processors.agent_activity",
                "tuckit.web.context_processors.entitlement_notice",
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
# Optional marketing-site URL. When set, the auth screens' wordmark links back
# to it (e.g. the landing page). Core ships empty (a self-host has no marketing
# site); cloud injects https://tuckit.dev via env. Keeps the public core free
# of any hardcoded cloud hostname.
TUCKIT_MARKETING_URL = env("TUCKIT_MARKETING_URL", default="") or ""
# Dotted path to a callable run right after signup, as hook(user=, org=).
# Core ships None (no-op); cloud sets it to attach billing. Never in core.
TUCKIT_SIGNUP_HOOK = env("TUCKIT_SIGNUP_HOOK", default=None) or None
# Dotted path to get_entitlements(org) -> Entitlements. Core ships None (all limits
# unlimited — self-host is unconstrained); cloud injects plan-based limits.
TUCKIT_ENTITLEMENTS_HOOK = env("TUCKIT_ENTITLEMENTS_HOOK", default=None) or None

# MCP request ceiling. A safety breaker, NOT a plan quota: the numbers are the
# same for every customer, nothing here goes through the entitlements hook, and
# it never appears on a price page. It exists so that one agent stuck in a loop
# cannot make an unbounded number of requests.
#
# Unlike the signup / entitlements / OAuth-token hooks above, this defaults ON
# for self-host too. Those are commercial limits, where unlimited is the right
# default for someone running their own server; a runaway agent is nobody's
# idea of a feature. Set a *_PER_SEC to 0 to switch that layer off.
#
# Connection layer: 120 burst, 3/sec sustained. The key is (client_id, user_id,
# org_id), stable across token rotation by design -- and therefore stable
# across concurrent sessions too, since this project's own policy is that one
# person runs several parallel agent sessions from a single client and user,
# so they all share one bucket. The headroom is for exactly that: a normal
# agent runs at 0.5-10 calls/min, so even six sessions at the top of that
# range sit well under the ceiling. A runaway loop stays bounded either way --
# 180/min sustained clamps a 10/sec loop to 3/sec, about 7.8M requests/month
# from one connection rather than unbounded.
# Org layer: a bound, not a budget -- a real 30-agent team peaks near 300/min
# against a 1200/min ceiling, so it only ever catches many connections at once.
TUCKIT_MCP_RATE_CONN_BURST = float(env("TUCKIT_MCP_RATE_CONN_BURST", default="120"))
TUCKIT_MCP_RATE_CONN_PER_SEC = float(env("TUCKIT_MCP_RATE_CONN_PER_SEC", default="3.0"))
TUCKIT_MCP_RATE_ORG_BURST = float(env("TUCKIT_MCP_RATE_ORG_BURST", default="2400"))
TUCKIT_MCP_RATE_ORG_PER_SEC = float(env("TUCKIT_MCP_RATE_ORG_PER_SEC", default="20.0"))

# OAuth 2.1 issuer/base URL for the MCP authorization server. Core default is
# empty -> derived from the incoming request origin (self-host needs no config).
# Cloud/reverse-proxy deploys set this to pin the public https origin. Keeps the
# public core free of any hardcoded cloud hostname (same rule as TUCKIT_MARKETING_URL).
TUCKIT_OAUTH_ISSUER = env("TUCKIT_OAUTH_ISSUER", default="") or ""

# Open Dynamic Client Registration (RFC 7591). Core default open — the public
# MCP client ecosystem (Claude Code, Cursor) relies on runtime self-registration.
# Cloud may set this false to require pre-registered clients.
TUCKIT_OAUTH_DCR_OPEN = env_bool("TUCKIT_OAUTH_DCR_OPEN", default=True)

# Dotted path to a callable run just before OAuth token issuance, as
# hook(user=, org=, client=). Core ships None (no-op -> unlimited). Cloud injects
# plan-entitlement checks (e.g. max connected apps) / audit logging; it raises
# tuckit.core.services.oauth_hook.TokenDenied to refuse. Mirrors the signup/
# entitlements hooks. Never billing code in core.
TUCKIT_OAUTH_TOKEN_HOOK = env("TUCKIT_OAUTH_TOKEN_HOOK", default=None) or None

# Social login (Google / GitHub). A provider is enabled only when BOTH its id and
# secret env vars are present. Core ships none configured -> the feature is simply
# off until a deployer sets these. No secrets or provider URLs live in code beyond
# the neutral registry in tuckit.core.services.social.providers.
def _social_provider(id_key, secret_key):
    cid = env(id_key, default="") or ""
    secret = env(secret_key, default="") or ""
    return {"client_id": cid, "client_secret": secret} if (cid and secret) else None


SOCIAL_PROVIDERS = {
    name: cfg
    for name, cfg in {
        "google": _social_provider("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"),
        "github": _social_provider("GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"),
    }.items()
    if cfg
}

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
# Django's own default here is "America/Chicago", which nobody ever chose: it
# is simply what global_settings ships. Every date the product renders — an
# activity timestamp, a shipped date, a deadline a deployment is counting down
# to — was being converted into it, so a reader outside that zone could be
# shown a date one off from the one on their own calendar.
#
# UTC is not a better guess at where anyone is; it is the absence of a guess,
# and it matches what the database stores. A deployment that knows where its
# people are sets this. Per-USER timezones are a different, larger thing and
# this is not a substitute for them.
TIME_ZONE = env("TUCKIT_TIME_ZONE", default="UTC")

# English UI: django's timesince/date filters render in English
# ("2 hours ago"), the framework default.
LANGUAGE_CODE = "en-us"
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
