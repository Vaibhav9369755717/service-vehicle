from routes.auth import auth_bp
from routes.customer import customer_bp
from routes.dashboard import dashboard_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(dashboard_bp)