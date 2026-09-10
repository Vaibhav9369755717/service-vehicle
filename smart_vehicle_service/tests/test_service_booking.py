from datetime import date, time, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import ServiceBooking, User, Vehicle, db


class BookingTestConfig(Config):
    TESTING = True
    SECRET_KEY = "booking-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(BookingTestConfig)
    with application.app_context():
        db.create_all()
        customer = User(
            name="Booking Customer",
            email="booking@example.com",
            phone="5550000300",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        other_customer = User(
            name="Other Customer",
            email="other-booking@example.com",
            phone="5550000301",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        db.session.add_all([customer, other_customer])
        db.session.flush()
        db.session.add_all(
            [
                Vehicle(
                    owner=customer,
                    registration_number="BOOK-001",
                    manufacturer="Aster",
                    model="Touring",
                    fuel_type="Hybrid",
                    mileage=12000,
                ),
                Vehicle(
                    owner=other_customer,
                    registration_number="OTHER-BOOK-001",
                    manufacturer="Private",
                    model="Vehicle",
                    fuel_type="Electric",
                    mileage=8000,
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
        data={"email": "booking@example.com", "password": "customer-pass"},
    )


def booking_data(vehicle_id, **overrides):
    data = {
        "vehicle_id": str(vehicle_id),
        "service_type": "General Service",
        "preferred_date": (date.today() + timedelta(days=4)).isoformat(),
        "preferred_time": "10:30",
        "complaint": "The vehicle is due for scheduled maintenance.",
        "additional_notes": "Please check the tire pressure.",
        "pickup_option": "Customer drop-off",
    }
    data.update(overrides)
    return data


def get_vehicle_id(app, registration_number):
    with app.app_context():
        return Vehicle.query.filter_by(registration_number=registration_number).one().id


def test_customer_can_create_list_and_view_booking(client, app):
    login_customer(client)
    vehicle_id = get_vehicle_id(app, "BOOK-001")

    create_response = client.post("/customer/book-service", data=booking_data(vehicle_id))

    assert create_response.status_code == 302
    with app.app_context():
        booking = ServiceBooking.query.one()
        booking_id = booking.id
        assert booking.status == "Requested"
        assert "Pickup/drop-off option: Customer drop-off" in booking.notes
        assert "Please check the tire pressure." in booking.notes

    list_response = client.get("/customer/bookings")
    detail_response = client.get(f"/customer/bookings/{booking_id}")

    assert list_response.status_code == 200
    assert b"General Service" in list_response.data
    assert b"BOOK-001" in list_response.data
    assert detail_response.status_code == 200
    assert b"Requested" in detail_response.data
    assert b"Customer drop-off" in detail_response.data
    assert b"Requested" in detail_response.data


def test_booking_validation_rejects_past_date_invalid_time_and_missing_fields(client, app):
    login_customer(client)
    vehicle_id = get_vehicle_id(app, "BOOK-001")

    past_response = client.post(
        "/customer/book-service",
        data=booking_data(vehicle_id, preferred_date=(date.today() - timedelta(days=1)).isoformat()),
    )
    invalid_time_response = client.post(
        "/customer/book-service",
        data=booking_data(vehicle_id, preferred_time="not-a-time"),
    )
    missing_response = client.post(
        "/customer/book-service",
        data=booking_data(vehicle_id, complaint=""),
    )

    assert past_response.status_code == 200
    assert b"cannot be in the past" in past_response.data
    assert invalid_time_response.status_code == 200
    assert b"valid time" in invalid_time_response.data
    assert missing_response.status_code == 200
    assert b"Customer complaint is required" in missing_response.data


def test_booking_rejects_vehicle_owned_by_another_customer(client, app):
    login_customer(client)
    other_vehicle_id = get_vehicle_id(app, "OTHER-BOOK-001")

    response = client.post(
        "/customer/book-service",
        data=booking_data(other_vehicle_id),
    )

    assert response.status_code == 200
    assert b"one of your vehicles" in response.data
    with app.app_context():
        assert ServiceBooking.query.count() == 0


def test_booking_conflict_is_rejected(client, app):
    login_customer(client)
    vehicle_id = get_vehicle_id(app, "BOOK-001")
    data = booking_data(vehicle_id)
    client.post("/customer/book-service", data=data)

    response = client.post("/customer/book-service", data=data)

    assert response.status_code == 200
    assert b"already has a booking" in response.data
    with app.app_context():
        assert ServiceBooking.query.count() == 1


def test_customer_cannot_view_another_customers_booking(client, app):
    with app.app_context():
        other = User.query.filter_by(email="other-booking@example.com").one()
        vehicle = Vehicle.query.filter_by(registration_number="OTHER-BOOK-001").one()
        booking = ServiceBooking(
            vehicle=vehicle,
            customer=other,
            service_type="Private service",
            booking_date=date.today() + timedelta(days=2),
            booking_time=time(9, 0),
            complaint="Private complaint",
            status="Requested",
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id
    login_customer(client)

    response = client.get(f"/customer/bookings/{booking_id}")

    assert response.status_code == 404
    assert b"Private complaint" not in response.data