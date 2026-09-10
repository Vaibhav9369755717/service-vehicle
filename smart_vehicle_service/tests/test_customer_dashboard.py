from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import (
    Invoice,
    Notification,
    ServiceBooking,
    ServiceRecord,
    User,
    Vehicle,
    db,
)


class DashboardTestConfig(Config):
    TESTING = True
    SECRET_KEY = "dashboard-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(DashboardTestConfig)
    with application.app_context():
        db.create_all()
        db.session.add_all(
            [
                User(
                    name="Dashboard Customer",
                    email="dashboard@example.com",
                    phone="5550000100",
                    password_hash=generate_password_hash("customer-pass"),
                    role="customer",
                ),
                User(
                    name="Other Customer",
                    email="other@example.com",
                    phone="5550000101",
                    password_hash=generate_password_hash("customer-pass"),
                    role="customer",
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


def login_customer(client):
    return client.post(
        "/auth/login",
        data={"email": "dashboard@example.com", "password": "customer-pass"},
    )


def add_dashboard_data(app):
    with app.app_context():
        customer = User.query.filter_by(email="dashboard@example.com").one()
        other_customer = User.query.filter_by(email="other@example.com").one()
        own_vehicle = Vehicle(
            owner=customer,
            registration_number="DASH-001",
            manufacturer="Aster",
            model="Touring",
            mileage=24000,
        )
        other_vehicle = Vehicle(
            owner=other_customer,
            registration_number="OTHER-001",
            manufacturer="Other Motors",
            model="Hidden",
            mileage=51000,
        )
        db.session.add_all([own_vehicle, other_vehicle])
        db.session.flush()

        own_upcoming = ServiceBooking(
            vehicle=own_vehicle,
            customer=customer,
            service_type="Scheduled maintenance",
            booking_date=date.today() + timedelta(days=3),
            booking_time=time(10, 30),
            status="confirmed",
        )
        own_active = ServiceBooking(
            vehicle=own_vehicle,
            customer=customer,
            service_type="Brake inspection",
            booking_date=date.today(),
            booking_time=time(8, 30),
            status="in_progress",
        )
        other_booking = ServiceBooking(
            vehicle=other_vehicle,
            customer=other_customer,
            service_type="Private service",
            booking_date=date.today() + timedelta(days=1),
            booking_time=time(9, 0),
            status="confirmed",
        )
        db.session.add_all([own_upcoming, own_active, other_booking])
        db.session.flush()
        db.session.add_all(
            [
                ServiceRecord(
                    booking=own_active,
                    vehicle=own_vehicle,
                    service_date=date.today() - timedelta(days=4),
                    work_performed="Oil and filter replacement",
                    mileage=23800,
                ),
                ServiceRecord(
                    booking=other_booking,
                    vehicle=other_vehicle,
                    service_date=date.today() - timedelta(days=2),
                    work_performed="Private repair details",
                    mileage=50000,
                ),
                Invoice(
                    booking=own_active,
                    vehicle=own_vehicle,
                    customer=customer,
                    invoice_number="INV-DASH-001",
                    status="unpaid",
                    subtotal=Decimal("100.00"),
                    tax=Decimal("10.00"),
                    total=Decimal("110.00"),
                ),
                Invoice(
                    booking=other_booking,
                    vehicle=other_vehicle,
                    customer=other_customer,
                    invoice_number="INV-OTHER-001",
                    status="paid",
                    total=Decimal("999.00"),
                ),
                Notification(
                    user=customer,
                    booking=own_upcoming,
                    title="Service reminder",
                    message="Your scheduled maintenance is coming up.",
                    created_at=datetime.utcnow(),
                ),
                Notification(
                    user=other_customer,
                    title="Private reminder",
                    message="This should not be visible.",
                ),
            ]
        )
        db.session.commit()


def test_customer_dashboard_shows_owned_dynamic_data_only(client, app):
    add_dashboard_data(app)
    login_customer(client)

    response = client.get("/customer/dashboard")

    assert response.status_code == 200
    assert b"DASH-001" in response.data
    assert b"Scheduled maintenance" in response.data
    assert b"Oil and filter replacement" in response.data
    assert b"INV-DASH-001" in response.data
    assert b"Service reminder" in response.data
    assert b"OTHER-001" not in response.data
    assert b"Private service" not in response.data
    assert b"INV-OTHER-001" not in response.data
    assert b"Private reminder" not in response.data


def test_empty_customer_dashboard_has_empty_states(client):
    login_customer(client)

    response = client.get("/customer/dashboard")

    assert response.status_code == 200
    assert b"No vehicles added yet" in response.data
    assert b"No upcoming service" in response.data
    assert b"No service history yet" in response.data


def test_logged_out_user_is_redirected_from_customer_dashboard(client):
    response = client.get("/customer/dashboard")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_non_customer_role_is_forbidden_from_customer_dashboard(client, app):
    with app.app_context():
        mechanic = User(
            name="Mechanic",
            email="mechanic-dashboard@example.com",
            phone="5550000102",
            password_hash=generate_password_hash("mechanic-pass"),
            role="mechanic",
        )
        db.session.add(mechanic)
        db.session.commit()

    response = client.post(
        "/auth/login",
        data={"email": "mechanic-dashboard@example.com", "password": "mechanic-pass"},
    )

    assert response.status_code == 302
    assert client.get("/customer/dashboard").status_code == 403


def test_customer_can_view_and_manage_owned_notifications(client, app):
    add_dashboard_data(app)
    login_customer(client)

    response = client.get("/customer/notifications")

    assert response.status_code == 200
    assert b"Service reminder" in response.data
    assert b"Mark as read" in response.data
    assert b"Private reminder" not in response.data

    with app.app_context():
        notification = Notification.query.filter_by(
            title="Service reminder"
        ).one()
        notification_id = notification.id
        booking_id = notification.booking_id

    response = client.get(f"/customer/notifications/{notification_id}")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        f"/customer/bookings/{booking_id}"
    )

    response = client.post(f"/customer/notifications/{notification_id}/read")

    assert response.status_code == 302
    with app.app_context():
        notification = db.session.get(Notification, notification_id)
        assert notification.is_read is True
        assert notification.read_at is not None


def test_customer_can_mark_all_notifications_read_and_cannot_access_other_users(client, app):
    add_dashboard_data(app)
    login_customer(client)

    with app.app_context():
        other_notification = Notification.query.filter_by(
            title="Private reminder"
        ).one()
        other_notification_id = other_notification.id

    assert client.post("/customer/notifications/read-all").status_code == 302
    with app.app_context():
        assert Notification.query.filter_by(is_read=False).count() == 1

    response = client.post(f"/customer/notifications/{other_notification_id}/read")

    assert response.status_code == 404