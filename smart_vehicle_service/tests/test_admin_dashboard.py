from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import Invoice, ServiceBooking, ServiceRecord, User, Vehicle, db


class AdminDashboardTestConfig(Config):
    TESTING = True
    SECRET_KEY = "admin-dashboard-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(AdminDashboardTestConfig)
    with application.app_context():
        db.create_all()
        admin = User(
            name="Dashboard Admin",
            email="dashboard-admin@example.com",
            password_hash=generate_password_hash("admin-pass"),
            role="admin",
        )
        customer = User(
            name="Dashboard Customer",
            email="dashboard-customer@example.com",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        mechanic = User(
            name="Dashboard Mechanic",
            email="dashboard-mechanic@example.com",
            password_hash=generate_password_hash("mechanic-pass"),
            role="mechanic",
        )
        db.session.add_all([admin, customer, mechanic])
        db.session.flush()
        vehicle = Vehicle(
            owner=customer,
            registration_number="ADMIN-001",
            manufacturer="Aster",
            model="Touring",
            mileage=25000,
        )
        db.session.add(vehicle)
        db.session.flush()
        bookings = [
            ServiceBooking(
                vehicle=vehicle,
                customer=customer,
                mechanic=mechanic,
                service_type="Brake Service",
                booking_date=date.today(),
                booking_time=time(9, 0),
                status="Requested",
            ),
            ServiceBooking(
                vehicle=vehicle,
                customer=customer,
                mechanic=mechanic,
                service_type="Oil Change",
                booking_date=date.today(),
                booking_time=time(10, 0),
                status="In Progress",
            ),
            ServiceBooking(
                vehicle=vehicle,
                customer=customer,
                mechanic=mechanic,
                service_type="General Service",
                booking_date=date.today() - timedelta(days=4),
                booking_time=time(11, 0),
                status="Completed",
            ),
        ]
        db.session.add_all(bookings)
        db.session.flush()
        db.session.add(
            ServiceRecord(
                booking=bookings[2],
                vehicle=vehicle,
                mechanic=mechanic,
                service_date=date.today() - timedelta(days=3),
                work_performed="Completed general service",
            )
        )
        db.session.add_all(
            [
                Invoice(
                    booking=bookings[2],
                    vehicle=vehicle,
                    customer=customer,
                    invoice_number="ADMIN-INV-001",
                    status="paid",
                    subtotal=Decimal("200.00"),
                    tax=Decimal("20.00"),
                    total=Decimal("220.00"),
                    paid_at=date.today(),
                ),
                Invoice(
                    booking=bookings[1],
                    vehicle=vehicle,
                    customer=customer,
                    invoice_number="ADMIN-INV-002",
                    status="unpaid",
                    subtotal=Decimal("100.00"),
                    tax=Decimal("10.00"),
                    total=Decimal("110.00"),
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


def login(client, email, password):
    return client.post("/auth/login", data={"email": email, "password": password})


def test_admin_dashboard_displays_statistics_charts_and_activity(client):
    login(client, "dashboard-admin@example.com", "admin-pass")

    response = client.get("/admin/dashboard")

    assert response.status_code == 200
    assert b"Total customers" in response.data
    assert b"Total vehicles" in response.data
    assert b"Total bookings" in response.data
    assert b"Pending bookings" in response.data
    assert b"Active services" in response.data
    assert b"Completed services" in response.data
    assert b"Total revenue" in response.data
    assert b"Pending payments" in response.data
    assert b"Total mechanics" in response.data
    assert b"Monthly bookings" in response.data
    assert b"Monthly revenue" in response.data
    assert b"Service types" in response.data
    assert b"Booking status" in response.data
    assert b"Dashboard Customer" in response.data
    assert b"Completed general service" in response.data
    assert b"ADMIN-INV-001" in response.data
    assert b"220.00" in response.data


def test_non_admin_cannot_access_admin_dashboard(client):
    login(client, "dashboard-customer@example.com", "customer-pass")

    response = client.get("/admin/dashboard")

    assert response.status_code == 403