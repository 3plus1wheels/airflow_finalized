from pathlib import Path
from datetime import timedelta
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key-change-before-production")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
USE_X_FORWARDED_HOST = os.getenv("DJANGO_USE_X_FORWARDED_HOST", "true").lower() == "true"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "corsheaders",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "storage_api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "minio_custom")),
        "USER": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "minio_custom")),
        "PASSWORD": os.getenv(
            "DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "minio_custom")
        ),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", os.getenv("POSTGRES_HOST_PORT", "5432")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "storage_api.authentication.CookieJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "720"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_DAYS", "14"))
    ),
}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = os.getenv("DJANGO_CORS_ALLOW_CREDENTIALS", "true").lower() == "true"
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        os.getenv(
            "DJANGO_CORS_ALLOWED_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ),
    ).split(",")
    if origin.strip()
]

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_PUBLIC_ENDPOINT = os.getenv("MINIO_PUBLIC_ENDPOINT", MINIO_ENDPOINT).rstrip("/")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

JWT_ACCESS_COOKIE_NAME = os.getenv("JWT_ACCESS_COOKIE_NAME", "access_token")
JWT_REFRESH_COOKIE_NAME = os.getenv("JWT_REFRESH_COOKIE_NAME", "refresh_token")
JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "false").lower() == "true"
JWT_COOKIE_SAMESITE = os.getenv("JWT_COOKIE_SAMESITE", "Lax")
