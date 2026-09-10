import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "phase-one-development-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///smart_vehicle_service.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False