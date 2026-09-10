from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import Invoice, Part, PartUsage, ServiceBooking, ServiceRecord, User, Vehicle, db


class ServiceHistoryTestConfig(Config):
    TESTING = True
    SECRET_KEY = "service-history-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(ServiceHistoryTestConfig)
    with application.app_context():
        db.create_all()
        customer = User(
            name="History Customer",
            email="history@example.com",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        other_customer = User(
            name="Other History Customer",
            email="other-history@example.com",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        mechanic = User(
            name="Alex Mechanic",
            email="mechanic-history@example.com",
            password_hash=generate_password_hash("mechanic-pass"),
            role="mechanic",
        )
        db.session.add_all([customer, other_customer, mechanic])
        db.session.flush()
        own_vehicle = Vehicle(
            owner=customer,
            registration_number="HIST-001",
            manufacturer="Aster",
            model="Touring",
            mileage=24000,
        )
        other_vehicle = Vehicle(
            owner=other_customer,
            registration_number="OTHER-HIST-001",
            manufacturer="Other Motors",
            model="Hidden",
            mileage=51000,
        )
        db.session.add_all([own_vehicle, other_vehicle])
        db.session.flush()

        completed_booking = ServiceBooking(
            vehicle=own_vehicle,
            customer=customer,
            mechanic=mechanic,
            service_type="Brake Service",
            booking_date=date.today() - timedelta(days=8),
            booking_time=time(9, 0),
            status="Completed",
        )
        active_booking = ServiceBooking(
            vehicle=own_vehicle,
            customer=customer,
            service_type="Oil Change",
            booking_date=date.today(),
            booking_time=time(10, 0),
            status="In Progress",
        )
        other_booking = ServiceBooking(
            vehicle=other_vehicle,
            customer=other_customer,
            service_type="Private Repair",
            booking_date=date.today() - timedelta(days=3),
            booking_time=time(11, 0),
            status="Completed",
        )
        db.session.add_all([completed_booking, active_booking, other_booking])
        db.session.flush()

        part = Part(
            name="Front brake pads",
            part_number="PAD-HIST-001",
            quantity_in_stock=10,
            unit_price=Decimal("75.00"),
        )
        db.session.add(part)
        db.session.flush()
        db.session.add_all(
            [
                ServiceRecord(
                    booking=completed_booking,
                    vehicle=own_vehicle,
                    mechanic=mechanic,
                    service_date=date.today() - timedelta(days=7),
                    work_performed="Replaced front brake pads",
                    diagnosis="Pads worn below recommended thickness",
                ),
                ServiceRecord(
                    booking=active_booking,
                    vehicle=own_vehicle,
                    mechanic=mechanic,
                    service_date=date.today(),
                    work_performed="Oil change in progress",
                ),
                ServiceRecord(
                    booking=other_booking,
                    vehicle=other_vehicle,
                    service_date=date.today() - timedelta(days=2),
                    work_performed="Private repair details",
                ),
            ]
        )
        db.session.flush()
        completed_record = ServiceRecord.query.filter_by(booking=completed_booking).one()
        db.session.add(
            PartUsage(
                part=part,
                service_record=completed_record,
                quantity=Decimal("1.00"),
                unit_cost=Decimal("75.00"),
            )
        )
        db.session.add(
            Invoice(
                booking=completed_booking,
                vehicle=own_vehicle,
                customer=customer,
                invoice_number="INV-HIST-001",
                status="paid",
                subtotal=Decimal("100.00"),
                tax=Decimal("20.00"),
                total=Decimal("120.00"),
            )
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
        data={"email": "history@example.com", "password": "customer-pass"},
    )


def get_record_id(app, booking_service_type):
    with app.app_context():
        return (
            ServiceRecord.query.join(ServiceBooking)
            .filter(ServiceBooking.service_type == booking_service_type)
            .one()
            .id
        )


def test_customer_history_shows_only_owned_completed_services(client, app):
    login_customer(client)

    response = client.get("/customer/service-history")

    assert response.status_code == 200
    assert b"Replaced front brake pads" in response.data
    assert b"Alex Mechanic" in response.data
    assert b"120.00" in response.data
    assert b"Private repair details" not in response.data
    assert b"Oil change in progress" not in response.data


def test_customer_history_filters_by_vehicle_type_and_date(client, app):
    login_customer(client)
    with app.app_context():
        vehicle_id = Vehicle.query.filter_by(registration_number="HIST-001").one().id

    response = client.get(
        "/customer/service-history",
        query_string={
            "vehicle_id": vehicle_id,
            "service_type": "Brake Service",
            "date_from": (date.today() - timedelta(days=10)).isoformat(),
            "date_to": date.today().isoformat(),
        },
    )

    assert response.status_code == 200
    assert b"Replaced front brake pads" in response.data
    assert b"value=\"Brake Service\" selected" in response.data


def test_customer_can_view_owned_service_detail_only(client, app):
    login_customer(client)
    record_id = get_record_id(app, "Brake Service")

    response = client.get(f"/customer/service-history/{record_id}")

    assert response.status_code == 200
    assert b"Service report" in response.data
    assert b"Front brake pads" in response.data
    assert b"INV-HIST-001" in response.data
    assert b"120.00" in response.data

    with app.app_context():
        other_record = (
            ServiceRecord.query.join(ServiceBooking)
            .filter(ServiceBooking.service_type == "Private Repair")
            .one()
        )
        active_record = (
            ServiceRecord.query.join(ServiceBooking)
            .filter(ServiceBooking.service_type == "Oil Change")
            .one()
        )

    assert client.get(f"/customer/service-history/{other_record.id}").status_code == 404
    assert client.get(f"/customer/service-history/{active_record.id}").status_code == 404