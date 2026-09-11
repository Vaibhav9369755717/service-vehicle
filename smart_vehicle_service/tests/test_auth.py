import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from config import Config
from models import User, db


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        db.session.add_all(
            [
                User(
                    name="Test Mechanic",
                    email="mechanic@example.com",
                    password_hash=generate_password_hash("mechanic-pass"),
                    phone="5550000001",
                    role="mechanic",
                ),
                User(
                    name="Test Admin",
                    email="admin@example.com",
                    password_hash=generate_password_hash("admin-pass"),
                    phone="5550000002",
                    role="admin",
                ),
            ]
        )
        db.session.commit()
    yield application
    with application.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def register_customer(client, email="customer@example.com"):
    return client.post(
        "/auth/register",
        data={
            "name": "Test Customer",
            "email": email,
            "phone": "5550000003",
            "password": "customer-pass",
            "confirm_password": "customer-pass",
        },
    )


def login(client, email, password):
    return client.post(
        "/auth/login", data={"email": email, "password": password}
    )


def test_registers_customer_with_hashed_password(client, app):
    response = register_customer(client)

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email="customer@example.com").one()
        assert user.role == "customer"
        assert user.password_hash != "customer-pass"
        assert check_password_hash(user.password_hash, "customer-pass")


def test_customer_login_redirects_to_customer_dashboard(client):
    register_customer(client)

    response = login(client, "customer@example.com", "customer-pass")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/customer/dashboard")


def test_logout_ends_session(client):
    register_customer(client)
    login(client, "customer@example.com", "customer-pass")

    response = client.post("/auth/logout")
    protected_response = client.get("/customer/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    assert protected_response.status_code == 302
    assert "/auth/login" in protected_response.headers["Location"]


def test_wrong_password_is_rejected(client):
    register_customer(client)

    response = login(client, "customer@example.com", "wrong-password")

    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_duplicate_email_is_rejected(client):
    register_customer(client)

    response = register_customer(client)

    assert response.status_code == 200
    assert b"already exists" in response.data


def test_logged_out_customer_page_redirects_to_login(client):
    response = client.get("/customer/dashboard")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_customer_cannot_access_admin_page(client):
    register_customer(client)
    login(client, "customer@example.com", "customer-pass")

    response = client.get("/admin/dashboard")

    assert response.status_code == 403
    assert b"Access denied" in response.data


def test_customer_cannot_access_mechanic_page(client):
    register_customer(client)
    login(client, "customer@example.com", "customer-pass")

    response = client.get("/mechanic/dashboard")

    assert response.status_code == 403


def test_admin_login_redirects_to_admin_dashboard(client):
    response = login(client, "admin@example.com", "admin-pass")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/dashboard")


def test_mechanic_login_redirects_to_mechanic_dashboard(client):
    response = login(client, "mechanic@example.com", "mechanic-pass")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/mechanic/dashboard")


def test_customer_can_view_and_edit_own_profile(client):
    register_customer(client)
    login(client, "customer@example.com", "customer-pass")

    profile_response = client.get("/auth/profile")
    assert profile_response.status_code == 200
    assert b"Profile" in profile_response.data

    update_response = client.post(
        "/auth/profile",
        data={
            "name": "Updated Customer",
            "email": "updated-customer@example.com",
            "phone": "+1 555 111 2222",
            "current_password": "customer-pass",
            "new_password": "",
            "confirm_password": "",
        },
        follow_redirects=False,
    )

    assert update_response.status_code == 302
    with client.application.app_context():
        user = User.query.filter_by(email="updated-customer@example.com").one()
        assert user.name == "Updated Customer"
        assert user.phone == "+1 555 111 2222"


def test_profile_password_change_requires_current_password(client):
    register_customer(client)
    login(client, "customer@example.com", "customer-pass")

    response = client.post(
        "/auth/profile",
        data={
            "name": "Customer Name",
            "email": "customer@example.com",
            "phone": "5550000003",
            "current_password": "wrong-password",
            "new_password": "new-secret-pass",
            "confirm_password": "new-secret-pass",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert b"Current password is incorrect" in response.data


def test_user_cannot_access_another_users_profile(client):
    register_customer(client)
    with client.application.app_context():
        other_user = User(
            name="Another User",
            email="another@example.com",
            password_hash=generate_password_hash("secret-pass"),
            phone="5550000999",
            role="customer",
        )
        db.session.add(other_user)
        db.session.commit()
        other_id = other_user.id

    login(client, "customer@example.com", "customer-pass")
    response = client.get(f"/auth/profile/{other_id}")

    assert response.status_code == 403


def test_session_cookie_has_security_flags(client):
    register_customer(client)
    response = login(client, "customer@example.com", "customer-pass")

    cookie_header = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie_header
    assert "SameSite=Lax" in cookie_header


def test_profile_post_without_csrf_token_is_rejected_when_enabled():
    application = create_app(TestConfig)
    application.config.update(TESTING=False, ENABLE_CSRF=True)

    with application.app_context():
        db.create_all()
        user = User(
            name="Secure Customer",
            email="secure@example.com",
            password_hash=generate_password_hash("secure-pass"),
            phone="5550000111",
            role="customer",
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = application.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["csrf_token"] = "expected-token"

    response = client.post(
        "/auth/profile",
        data={
            "name": "Secure Customer",
            "email": "secure@example.com",
            "phone": "5550000111",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400