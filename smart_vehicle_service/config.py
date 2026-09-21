import os
from datetime import timedelta


def _truthy(value):
    return str(value).lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "smart-vehicle-local-dev-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///smart_vehicle_service.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _truthy(os.environ.get("SESSION_COOKIE_SECURE", "false"))
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    ENABLE_CSRF = not _truthy(os.environ.get("DISABLE_CSRF", "false"))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    PROPAGATE_EXCEPTIONS = False


class ProductionConfig(Config):
    ENV = "production"
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    @classmethod
    def validate(cls):
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError("SECRET_KEY environment variable is required in production.")
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError("DATABASE_URL environment variable is required in production.")