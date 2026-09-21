import logging
import os


from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

try:
    from smart_vehicle_service.auth import login_manager
    from smart_vehicle_service.config import Config, ProductionConfig
    from smart_vehicle_service.models import Notification, db
    from smart_vehicle_service.routes import register_blueprints
except ImportError:  # pragma: no cover - local development fallback
    from auth import login_manager
    from config import Config, ProductionConfig
    from models import Notification, db
    from routes import register_blueprints


load_dotenv()


def create_app(config_class=None):
    if config_class is None:
        config_class = ProductionConfig if os.environ.get("FLASK_ENV") == "production" else Config
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    if app.config.get("ENV") == "production":
        ProductionConfig.validate()
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_SECURE", not app.debug and not app.config.get("TESTING", False))
    app.config.setdefault("ENABLE_CSRF", not app.config.get("TESTING", False))
    app.config.setdefault("LOG_LEVEL", "INFO")

    logging.basicConfig(
        level=getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.logger.setLevel(getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO))

    db.init_app(app)
    login_manager.init_app(app)
    register_blueprints(app)

    @app.context_processor
    def inject_security_context():
        unread_count = 0

        if current_user.is_authenticated and current_user.role == "customer":
            unread_count = Notification.query.filter_by(
                user_id=current_user.id,
                is_read=False
            ).count()

        return {
            "unread_notification_count": unread_count,
        }

    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


    @app.route("/")
    def home():
        return render_template("base.html", page_title="Smart Vehicle Service")

    @app.route("/dashboard")
    @login_required
    def dashboard_redirect():
        dashboard_endpoints = {
            "customer": "customer.customer_dashboard",
            "mechanic": "dashboard.mechanic_dashboard",
            "admin": "dashboard.admin_dashboard",
        }
        endpoint = dashboard_endpoints.get(current_user.role, "home")
        return redirect(url_for(endpoint))

    @app.errorhandler(403)
    def forbidden(error):
        return render_template(
            "errors/403.html",
            page_title="Access denied",
            dashboard_endpoint=("dashboard_redirect" if current_user.is_authenticated else "auth.login"),
        ), 403

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/403.html", page_title="Bad request"), 400

    @app.errorhandler(500)
    def internal_server_error(error):
        app.logger.exception("Unhandled server error: %s", error)
        return render_template("errors/403.html", page_title="Server error"), 500

    @app.cli.command("init-db")
    def init_db_command():
        """Create all database tables."""
        init_database(app)
        print("Initialized the database.")

    return app


def init_database(app):
    with app.app_context():
        db.create_all()
        add_missing_columns()


def add_missing_columns():
    migration_columns = {
        "parts": {
            "category": "VARCHAR(80)",
            "supplier": "VARCHAR(120)",
            "minimum_stock": "INTEGER NOT NULL DEFAULT 0",
            "purchase_price": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "selling_price": "NUMERIC(12, 2)",
        },
        "inspections": {"recommendations": "TEXT"},
        "notifications": {
            "booking_id": "INTEGER",
            "invoice_id": "INTEGER",
        },
        "payments": {
            "invoice_id": "INTEGER NOT NULL",
            "customer_id": "INTEGER NOT NULL",
            "payment_reference": "VARCHAR(80) NOT NULL",
            "transaction_id": "VARCHAR(80) NOT NULL",
            "amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "status": "VARCHAR(30) NOT NULL DEFAULT 'pending'",
            "payment_method": "VARCHAR(50) NOT NULL DEFAULT 'internal_mock'",
            "payment_date": "DATETIME",
            "notes": "TEXT",
        },
        "users": {"specialization": "VARCHAR(120)"},
        "service_records": {
            "customer_id": "INTEGER",
            "invoice_id": "INTEGER",
            "service_type": "VARCHAR(100) NOT NULL DEFAULT 'General Service'",
            "inspection_results": "TEXT",
            "labor_charges": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "additional_charges": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "total_cost": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
        },
    }
    inspector = inspect(db.engine)
    with db.engine.begin() as connection:
        for table_name, columns in migration_columns.items():
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    )
            if table_name == "parts" and "minimum_stock" not in existing_columns:
                connection.execute(text("UPDATE parts SET minimum_stock = reorder_level"))


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)