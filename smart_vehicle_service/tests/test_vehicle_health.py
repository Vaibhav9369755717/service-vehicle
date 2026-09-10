from datetime import date, time, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import (
    Inspection,
    InspectionItem,
    ServiceBooking,
    ServiceRecord,
    User,
    Vehicle,
    db,
)


class VehicleHealthTestConfig(Config):
    TESTING = True
    SECRET_KEY = "vehicle-health-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(VehicleHealthTestConfig)
    with application.app_context():
        db.create_all()
        customer = User(
            name="Health Customer",
            email="health@example.com",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        other_customer = User(
            name="Other Health Customer",
            email="other-health@example.com",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        db.session.add_all([customer, other_customer])
        db.session.flush()
        own_vehicle = Vehicle(
            owner=customer,
            registration_number="HEALTH-001",
            manufacturer="Aster",
            model="Touring",
            mileage=42000,
        )
        other_vehicle = Vehicle(
            owner=other_customer,
            registration_number="OTHER-HEALTH-001",
            manufacturer="Private",
            model="Hidden",
            mileage=10000,
        )
        db.session.add_all([own_vehicle, other_vehicle])
        db.session.flush()
        own_booking = ServiceBooking(
            vehicle=own_vehicle,
            customer=customer,
            service_type="Brake Service",
            booking_date=date.today() - timedelta(days=200),
            booking_time=time(9, 0),
            status="Completed",
        )
        other_booking = ServiceBooking(
            vehicle=other_vehicle,
            customer=other_customer,
            service_type="Private Service",
            booking_date=date.today() - timedelta(days=10),
            booking_time=time(9, 0),
            status="Completed",
        )
        db.session.add_all([own_booking, other_booking])
        db.session.flush()
        db.session.add_all(
            [
                ServiceRecord(
                    booking=own_booking,
                    vehicle=own_vehicle,
                    service_date=date.today() - timedelta(days=190),
                    mileage=40000,
                    work_performed="Replaced brake pads",
                ),
                ServiceRecord(
                    booking=other_booking,
                    vehicle=other_vehicle,
                    service_date=date.today() - timedelta(days=9),
                    work_performed="Private work",
                ),
            ]
        )
        inspection = Inspection(
            booking=own_booking,
            vehicle=own_vehicle,
            overall_status="warning",
            notes="Brake wear needs attention.",
            inspected_at=None,
        )
        db.session.add(inspection)
        db.session.flush()
        db.session.add_all(
            [
                InspectionItem(
                    inspection=inspection,
                    item_name="Brakes",
                    status="warning",
                    notes="Pads nearing limit",
                ),
                InspectionItem(
                    inspection=inspection,
                    item_name="Engine",
                    status="pass",
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
        data={"email": "health@example.com", "password": "customer-pass"},
    )


def vehicle_id(app, registration_number):
    with app.app_context():
        return Vehicle.query.filter_by(registration_number=registration_number).one().id


def test_customer_can_view_vehicle_health_and_maintenance_history(client, app):
    login_customer(client)
    own_vehicle_id = vehicle_id(app, "HEALTH-001")

    response = client.get(f"/customer/vehicles/{own_vehicle_id}/health")

    assert response.status_code == 200
    assert b"Overall vehicle health" in response.data
    assert b"Needs Attention" in response.data
    assert b"Brakes" in response.data
    assert b"Engine" in response.data
    assert b"40,000" in response.data
    assert b"Replaced brake pads" in response.data
    assert b"Routine service recommended" in response.data


def test_dashboard_shows_owned_maintenance_reminder(client, app):
    login_customer(client)

    response = client.get("/customer/dashboard")

    assert response.status_code == 200
    assert b"Maintenance reminders" in response.data
    assert b"OTHER-HEALTH-001" not in response.data
    assert b"Routine service recommended" in response.data


def test_customer_cannot_view_another_customers_vehicle_health(client, app):
    login_customer(client)
    other_vehicle_id = vehicle_id(app, "OTHER-HEALTH-001")

    response = client.get(f"/customer/vehicles/{other_vehicle_id}/health")

    assert response.status_code == 404