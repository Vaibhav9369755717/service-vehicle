try:
    from smart_vehicle_service.routes.auth import auth_bp
    from smart_vehicle_service.routes.customer import customer_bp
    from smart_vehicle_service.routes.dashboard import dashboard_bp
except ImportError:  # pragma: no cover - local development fallback
    from routes.auth import auth_bp
    from routes.customer import customer_bp
    from routes.dashboard import dashboard_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(dashboard_bp)