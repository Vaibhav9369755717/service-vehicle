from datetime import date, time, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import Notification, ServiceBooking, User, Vehicle, db


class AdminBookingTestConfig(Config):
    TESTING = True
    SECRET_KEY = "admin-booking-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(AdminBookingTestConfig)
    with application.app_context():
        db.create_all()
        admin = User(name="Booking Admin", email="booking-admin@example.com", password_hash=generate_password_hash("admin-pass"), role="admin")
        customer = User(name="Booking Customer", email="booking-customer@example.com", password_hash=generate_password_hash("customer-pass"), role="customer")
        mechanic = User(name="Booking Mechanic", email="booking-mechanic@example.com", password_hash=generate_password_hash("mechanic-pass"), role="mechanic", specialization="Brakes and diagnostics")
        second_mechanic = User(name="Second Mechanic", email="second-mechanic@example.com", password_hash=generate_password_hash("mechanic-pass"), role="mechanic", specialization="Engine service")
        db.session.add_all([admin, customer, mechanic, second_mechanic])
        db.session.flush()
        vehicle = Vehicle(owner=customer, registration_number="ADMIN-BOOK-001", manufacturer="Aster", model="Touring", mileage=12000)
        db.session.add(vehicle)
        db.session.flush()
        db.session.add_all([
            ServiceBooking(vehicle=vehicle, customer=customer, service_type="Brake Service", booking_date=date.today() + timedelta(days=2), booking_time=time(9, 0), complaint="Brake noise", status="Requested"),
            ServiceBooking(vehicle=vehicle, customer=customer, service_type="Oil Change", booking_date=date.today() + timedelta(days=4), booking_time=time(10, 0), complaint="Oil due", status="Requested"),
        ])
        db.session.commit()
    yield application
    with application.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def booking_id(app, service_type):
    with app.app_context():
        return ServiceBooking.query.filter_by(service_type=service_type).one().id


def test_admin_can_search_filter_and_open_bookings(client, app):
    login(client, "booking-admin@example.com", "admin-pass")
    target_id = booking_id(app, "Brake Service")

    response = client.get("/admin/bookings", query_string={"service_type": "Brake Service", "status": "Requested"})
    detail = client.get(f"/admin/bookings/{target_id}")

    assert response.status_code == 200
    assert b"Brake Service" in response.data
    assert b"<small>Oil Change</small>" not in response.data
    assert detail.status_code == 200
    assert b"Brake noise" in detail.data
    assert b"Brakes and diagnostics" in detail.data
    assert b"Available mechanics" in detail.data


def test_admin_can_approve_reschedule_assign_and_change_status(client, app):
    login(client, "booking-admin@example.com", "admin-pass")
    target_id = booking_id(app, "Brake Service")
    new_date = (date.today() + timedelta(days=7)).isoformat()

    assert client.post(f"/admin/bookings/{target_id}/approve").status_code == 302
    assert client.post(f"/admin/bookings/{target_id}/reschedule", data={"booking_date": new_date, "booking_time": "14:30"}).status_code == 302
    with app.app_context():
        mechanic_id = User.query.filter_by(email="booking-mechanic@example.com").one().id
    assert client.post(f"/admin/bookings/{target_id}/assign", data={"mechanic_id": mechanic_id}).status_code == 302
    assignment_detail = client.get(f"/admin/bookings/{target_id}")
    assert b"Current active jobs" in assignment_detail.data
    assert b"Brake Service" in assignment_detail.data
    assert client.post(f"/admin/bookings/{target_id}/status", data={"status": "In Progress"}).status_code == 302

    with app.app_context():
        booking = db.session.get(ServiceBooking, target_id)
        assert booking.status == "In Progress"
        assert booking.booking_date == date.today() + timedelta(days=7)
        assert booking.booking_time == time(14, 30)
        assert booking.mechanic_id == mechanic_id
        notifications = Notification.query.filter_by(booking_id=target_id).all()
        assert {notification.notification_type for notification in notifications} >= {"booking_approved", "booking_rescheduled", "mechanic_assigned", "booking_status"}
        assert Notification.query.filter_by(user_id=mechanic_id, booking_id=target_id).count() == 1


def test_admin_can_reject_booking_and_non_admin_is_denied(client, app):
    target_id = booking_id(app, "Oil Change")
    login(client, "booking-admin@example.com", "admin-pass")

    assert client.post(f"/admin/bookings/{target_id}/reject").status_code == 302
    with app.app_context():
        assert db.session.get(ServiceBooking, target_id).status == "Rejected"
        assert Notification.query.filter_by(booking_id=target_id, notification_type="booking_rejected").count() == 1

    client.post("/auth/logout")
    login(client, "booking-customer@example.com", "customer-pass")
    assert client.get("/admin/bookings").status_code == 403


def test_admin_can_reassign_and_remove_mechanic_assignment(client, app):
    login(client, "booking-admin@example.com", "admin-pass")
    target_id = booking_id(app, "Brake Service")
    with app.app_context():
        first_id = User.query.filter_by(email="booking-mechanic@example.com").one().id
        second_id = User.query.filter_by(email="second-mechanic@example.com").one().id

    client.post(f"/admin/bookings/{target_id}/assign", data={"mechanic_id": first_id})
    client.post(f"/admin/bookings/{target_id}/assign", data={"mechanic_id": second_id})
    with app.app_context():
        assert db.session.get(ServiceBooking, target_id).mechanic_id == second_id
        assert Notification.query.filter_by(user_id=first_id, notification_type="job_reassigned").count() == 1

    assert client.post(f"/admin/bookings/{target_id}/remove-assignment").status_code == 302
    with app.app_context():
        booking = db.session.get(ServiceBooking, target_id)
        assert booking.mechanic_id is None
        assert booking.status == "Approved"
        assert Notification.query.filter_by(notification_type="job_unassigned", booking_id=target_id).count() == 1