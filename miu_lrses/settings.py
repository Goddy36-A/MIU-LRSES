"""Django settings for MIU-LRSES (development configuration).

See README.md, section "Security limitations", before any public deployment.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# DEVELOPMENT DEFAULTS. Override with environment variables in any shared setup.
SECRET_KEY = os.environ.get(
    "MIU_LRSES_SECRET_KEY",
    "dev-only-insecure-key-change-me-before-any-deployment",
)
DEBUG = os.environ.get("MIU_LRSES_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("MIU_LRSES_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.accounts",
    "apps.academics",
    "apps.timetables",
    "apps.reminders",
    "apps.attendance",
    "apps.performance",
    "apps.research",
    "apps.questionnaires",
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

ROOT_URLCONF = "miu_lrses.urls"

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
                "apps.reminders.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "miu_lrses.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Authentication flow
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Sessions: expire after 8 hours; cookie not readable by JavaScript.
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Email: development prints messages (e.g. password-reset links) to the console.
# No real email is sent unless you configure SMTP yourself.
EMAIL_BACKEND = os.environ.get(
    "MIU_LRSES_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = "MIU-LRSES <no-reply@localhost>"

# Reminder delivery channels. Only "in_app" is implemented (see apps/reminders/channels.py).
REMINDER_CHANNELS = ["in_app"]

if not DEBUG:  # pragma: no cover - production hardening switches
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000

# Tests only: PBKDF2 with fewer iterations keeps the automated test run short (same hash format).
# Never used when running the server.
if "test" in sys.argv:
    PASSWORD_HASHERS = ["miu_lrses.test_hashers.FastPBKDF2PasswordHasher"]
