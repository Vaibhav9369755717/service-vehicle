from datetime import date

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import User, Vehicle, db


class VehicleTestConfig(Config):
    TESTING = True
    SECRET_KEY = "vehicle-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(VehicleTestConfig)
    with application.app_context():
        db.create_all()
        db.session.add_all(
            [
                User(
                    name="Vehicle Customer",
                    email="vehicle@example.com",
                    phone="5550000200",
                    password_hash=generate_password_hash("customer-pass"),
                    role="customer",
                ),
                User(
                    name="Other Customer",
                    email="other-vehicle@example.com",
                    phone="5550000201",
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
        data={"email": "vehicle@example.com", "password": "customer-pass"},
    )


def vehicle_data(**overrides):
    data = {
        "registration_number": "VEH-001",
        "manufacturer": "Aster",
        "model": "Touring",
        "variant": "Sport",
        "year": str(date.today().year),
        "fuel_type": "Hybrid",
        "mileage": "12000",
        "vin": "1HGCM82633A123456",
        "color": "Blue",
    }
    data.update(overrides)
    return data


def test_customer_can_add_edit_view_and_delete_vehicle(client, app):
    login_customer(client)

    add_response = client.post("/customer/vehicles/add", data=vehicle_data())
    assert add_response.status_code == 302
    with app.app_context():
        vehicle = Vehicle.query.filter_by(registration_number="VEH-001").one()
        vehicle_id = vehicle.id

    detail_response = client.get(f"/customer/vehicles/{vehicle_id}")
    edit_response = client.post(
        f"/customer/vehicles/{vehicle_id}/edit",
        data=vehicle_data(registration_number="VEH-002", mileage="12500"),
    )
    delete_response = client.post(f"/customer/vehicles/{vehicle_id}/delete")

    assert b"Aster Touring" in detail_response.data
    assert edit_response.status_code == 302
    assert delete_response.status_code == 302
    with app.app_context():
        assert db.session.get(Vehicle, vehicle_id) is None


def test_vehicle_list_only_contains_current_customers_vehicles(client, app):
    with app.app_context():
        owner = User.query.filter_by(email="vehicle@example.com").one()
        other = User.query.filter_by(email="other-vehicle@example.com").one()
        db.session.add_all(
            [
                Vehicle(
                    owner=owner,
                    registration_number="OWN-001",
                    manufacturer="Aster",
                    model="Mine",
                    fuel_type="Petrol",
                    mileage=100,
                ),
                Vehicle(
                    owner=other,
                    registration_number="OTHER-001",
                    manufacturer="Hidden",
                    model="Not Mine",
                    fuel_type="Diesel",
                    mileage=100,
                ),
            ]
        )
        db.session.commit()
    login_customer(client)

    response = client.get("/customer/vehicles")

    assert response.status_code == 200
    assert b"OWN-001" in response.data
    assert b"OTHER-001" not in response.data


def test_vehicle_validation_rejects_invalid_values_and_duplicates(client, app):
    login_customer(client)
    client.post("/customer/vehicles/add", data=vehicle_data())

    duplicate_response = client.post("/customer/vehicles/add", data=vehicle_data())
    invalid_response = client.post(
        "/customer/vehicles/add",
        data=vehicle_data(
            registration_number="VEH-003",
            vin="1HGCM82633A654321",
            year="1800",
            mileage="-1",
        ),
    )

    assert duplicate_response.status_code == 200
    assert b"already in use" in duplicate_response.data
    assert invalid_response.status_code == 200
    assert b"Manufacturing year must be between" in invalid_response.data
    assert b"Mileage cannot be negative" in invalid_response.data


def test_duplicate_vin_is_rejected(client):
    login_customer(client)
    client.post("/customer/vehicles/add", data=vehicle_data())

    response = client.post(
        "/customer/vehicles/add",
        data=vehicle_data(registration_number="VEH-004"),
    )

    assert response.status_code == 200
    assert b"VIN/chassis number is already in use" in response.data


def test_customer_cannot_access_another_customers_vehicle(client, app):
    with app.app_context():
        other = User.query.filter_by(email="other-vehicle@example.com").one()
        vehicle = Vehicle(
            owner=other,
            registration_number="PRIVATE-001",
            manufacturer="Private",
            model="Vehicle",
            fuel_type="Electric",
            mileage=50,
        )
        db.session.add(vehicle)
        db.session.commit()
        vehicle_id = vehicle.id
    login_customer(client)

    detail_response = client.get(f"/customer/vehicles/{vehicle_id}")
    edit_response = client.get(f"/customer/vehicles/{vehicle_id}/edit")
    delete_response = client.post(f"/customer/vehicles/{vehicle_id}/delete")

    assert detail_response.status_code == 404
    assert edit_response.status_code == 404
    assert delete_response.status_code == 404