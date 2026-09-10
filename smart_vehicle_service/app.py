from flask import Flask, render_template
from flask_login import current_user
from sqlalchemy import inspect, text

from auth import login_manager
from config import Config
from models import Notification, db
from routes import register_blueprints


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    db.init_app(app)
    login_manager.init_app(app)
    register_blueprints(app)

    @app.context_processor
    def customer_notification_count():
        unread_count = 0
        if current_user.is_authenticated and current_user.role == "customer":
            unread_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
        return {"unread_notification_count": unread_count}

    @app.route("/")
    def home():
        return render_template("base.html", page_title="Smart Vehicle Service")

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html", page_title="Access denied"), 403

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
    app.run(debug=True)