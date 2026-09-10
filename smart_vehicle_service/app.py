from flask import Flask, render_template

from auth import login_manager
from config import Config
from models import db
from routes import register_blueprints


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    db.init_app(app)
    login_manager.init_app(app)
    register_blueprints(app)

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


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)