from flask_login import LoginManager

try:
    from smart_vehicle_service.models import User, db
except ImportError:  # pragma: no cover - local development fallback
    from models import User, db


login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access that page."
login_manager.login_message_category = "error"


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None