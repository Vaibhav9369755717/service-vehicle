from datetime import date, time, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import Inspection, Invoice, Notification, Part, PartUsage, ServiceBooking, ServiceRecord, User, Vehicle, db


class MechanicDashboardTestConfig(Config):
    TESTING = True
    SECRET_KEY = "mechanic-dashboard-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(MechanicDashboardTestConfig)
    with application.app_context():
        db.create_all()
        customer = User(
            name="Workshop Customer",
            email="workshop-customer@example.com",
            password_hash=generate_password_hash("customer-pass"),
            role="customer",
        )
        mechanic = User(
            name="Assigned Mechanic",
            email="assigned-mechanic@example.com",
            password_hash=generate_password_hash("mechanic-pass"),
            role="mechanic",
        )
        other_mechanic = User(
            name="Other Mechanic",
            email="other-mechanic@example.com",
            password_hash=generate_password_hash("mechanic-pass"),
            role="mechanic",
        )
        admin = User(
            name="Workshop Admin",
            email="workshop-admin@example.com",
            password_hash=generate_password_hash("admin-pass"),
            role="admin",
        )
        db.session.add_all([customer, mechanic, other_mechanic, admin])
        db.session.flush()
        vehicle = Vehicle(
            owner=customer,
            registration_number="MECH-001",
            manufacturer="Aster",
            model="Touring",
            mileage=22000,
        )
        other_vehicle = Vehicle(
            owner=customer,
            registration_number="MECH-002",
            manufacturer="Nova",
            model="City",
            mileage=18000,
        )
        db.session.add_all([vehicle, other_vehicle])
        db.session.flush()
        assigned_job = ServiceBooking(
            vehicle=vehicle,
            customer=customer,
            mechanic=mechanic,
            service_type="Brake Service",
            booking_date=date.today(),
            booking_time=time(9, 30),
            complaint="Brake noise",
            status="Requested",
        )
        other_job = ServiceBooking(
            vehicle=other_vehicle,
            customer=customer,
            mechanic=other_mechanic,
            service_type="Oil Change",
            booking_date=date.today() + timedelta(days=1),
            booking_time=time(10, 0),
            status="Requested",
        )
        db.session.add_all([assigned_job, other_job])
        db.session.add(
            Part(
                name="Brake pad set",
                part_number="MECH-PAD-001",
                quantity_in_stock=8,
                unit_price=75,
            )
        )
        db.session.commit()
    yield application
    with application.app_context():
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password):
    return client.post(
        "/auth/login", data={"email": email, "password": password}
    )


def job_id(app, service_type):
    with app.app_context():
        return ServiceBooking.query.filter_by(service_type=service_type).one().id


def vehicle_id(app, registration_number):
    with app.app_context():
        return Vehicle.query.filter_by(registration_number=registration_number).one().id


def test_mechanic_sees_only_assigned_jobs_and_dashboard_sections(client, app):
    login(client, "assigned-mechanic@example.com", "mechanic-pass")

    response = client.get("/mechanic/dashboard")
    jobs_response = client.get("/mechanic/jobs")

    assert response.status_code == 200
    assert b"Today&apos;s assigned jobs" in response.data
    assert b"Vehicle inspections" in response.data
    assert b"Basic" not in response.data
    assert b"Brake Service" in jobs_response.data
    assert b"Oil Change" not in jobs_response.data


def test_mechanic_can_accept_start_and_complete_assigned_job(client, app):
    login(client, "assigned-mechanic@example.com", "mechanic-pass")
    assigned_id = job_id(app, "Brake Service")

    assert client.post(f"/mechanic/jobs/{assigned_id}/accept").status_code == 302
    with app.app_context():
        assert db.session.get(ServiceBooking, assigned_id).status == "Accepted"

    assert client.post(f"/mechanic/jobs/{assigned_id}/start").status_code == 302
    with app.app_context():
        part_id = Part.query.filter_by(part_number="MECH-PAD-001").one().id
    response = client.post(
        f"/mechanic/jobs/{assigned_id}/complete",
        data={
            "work_performed": "Replaced brake pads",
            "diagnosis": "Pads worn",
            "mileage": "22500",
            "notes": "Road tested successfully",
            "part_id": str(part_id),
            "quantity": "2",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        job = db.session.get(ServiceBooking, assigned_id)
        assert job.status == "Completed"
        assert ServiceRecord.query.filter_by(booking_id=assigned_id).one().work_performed == "Replaced brake pads"
        notification = Notification.query.filter_by(booking_id=assigned_id).one()
        assert notification.title == "Service completed"
        usage = PartUsage.query.filter_by(service_record_id=ServiceRecord.query.filter_by(booking_id=assigned_id).one().id).one()
        assert usage.quantity == 2
        assert Part.query.get(part_id).quantity_in_stock == 6
        record = ServiceRecord.query.filter_by(booking_id=assigned_id).one()
        assert record.customer_id == job.customer_id
        assert record.invoice_id is not None
        assert record.total_cost == 150

    edit_response = client.post(
        f"/mechanic/jobs/{assigned_id}/service-record/edit",
        data={
            "work_performed": "Replaced brake pads and tested system",
            "diagnosis": "Pads worn",
            "labor_charges": "50.00",
            "additional_charges": "10.00",
            "notes": "Updated record",
        },
    )
    assert edit_response.status_code == 302
    with app.app_context():
        record = ServiceRecord.query.filter_by(booking_id=assigned_id).one()
        assert record.work_performed == "Replaced brake pads and tested system"
        assert record.total_cost == 210

    client.post("/auth/logout")
    login(client, "workshop-admin@example.com", "admin-pass")
    admin_records = client.get("/admin/service-records")
    assert admin_records.status_code == 200
    assert b"Replaced brake pads and tested system" in admin_records.data


def test_mechanic_cannot_open_or_update_another_mechanics_job(client, app):
    login(client, "assigned-mechanic@example.com", "mechanic-pass")
    other_id = job_id(app, "Oil Change")

    assert client.get(f"/mechanic/jobs/{other_id}").status_code == 404
    assert client.post(f"/mechanic/jobs/{other_id}/accept").status_code == 404


def test_admin_can_view_all_mechanic_jobs(client, app):
    login(client, "workshop-admin@example.com", "admin-pass")

    response = client.get("/mechanic/jobs")

    assert response.status_code == 200
    assert b"Brake Service" in response.data
    assert b"Oil Change" in response.data


def test_admin_can_manage_inventory_and_filter_stock(client, app):
    login(client, "workshop-admin@example.com", "admin-pass")

    add_response = client.post(
        "/admin/inventory/add",
        data={
            "name": "Cabin air filter",
            "part_number": "MECH-FILTER-001",
            "category": "Filters",
            "supplier": "Parts Direct",
            "quantity_in_stock": "2",
            "minimum_stock": "5",
            "purchase_price": "12.50",
            "selling_price": "24.00",
            "description": "Cabin filter",
        },
    )

    assert add_response.status_code == 302
    low_response = client.get("/admin/inventory?stock=low")
    assert b"Cabin air filter" in low_response.data
    assert b"Low Stock" in low_response.data
    assert b"Parts Direct" in low_response.data

    with app.app_context():
        new_part = Part.query.filter_by(part_number="MECH-FILTER-001").one()
        new_part_id = new_part.id

    edit_response = client.post(
        f"/admin/inventory/{new_part_id}/edit",
        data={
            "name": "Cabin air filter",
            "part_number": "MECH-FILTER-001",
            "category": "Filters",
            "supplier": "Parts Direct",
            "quantity_in_stock": "0",
            "minimum_stock": "5",
            "purchase_price": "12.50",
            "selling_price": "24.00",
            "description": "Cabin filter",
        },
    )
    assert edit_response.status_code == 302
    assert b"Out of Stock" in client.get("/admin/inventory?stock=out").data

    assert client.post(f"/admin/inventory/{new_part_id}/delete").status_code == 302
    with app.app_context():
        assert db.session.get(Part, new_part_id) is None


def test_mechanic_cannot_manage_inventory(client, app):
    login(client, "assigned-mechanic@example.com", "mechanic-pass")

    assert client.get("/admin/inventory").status_code == 403
    assert client.post("/admin/inventory/add", data={}).status_code == 403


def test_mechanic_can_save_update_and_customer_can_view_inspection(client, app):
    login(client, "assigned-mechanic@example.com", "mechanic-pass")
    assigned_id = job_id(app, "Brake Service")
    statuses = {
        "engine": "Good",
        "brakes": "Needs Attention",
        "tyres": "Good",
        "battery": "Good",
        "suspension": "Good",
        "lights": "Good",
        "engine_oil": "Good",
        "coolant": "Good",
        "ac": "Good",
        "overall_condition": "Needs Attention",
    }
    inspection_data = {f"status_{key}": value for key, value in statuses.items()}
    inspection_data.update(
        {"notes": "Brake wear recorded.", "recommendations": "Replace pads at the next visit."}
    )

    response = client.post(
        f"/mechanic/jobs/{assigned_id}/inspection", data=inspection_data
    )

    assert response.status_code == 302
    with app.app_context():
        inspection = Inspection.query.filter_by(booking_id=assigned_id).one()
        assert inspection.overall_status == "Needs Attention"
        assert len(inspection.items) == 10
        inspection_id = inspection.id

    inspection_data["status_brakes"] = "Critical"
    update_response = client.post(
        f"/mechanic/jobs/{assigned_id}/inspection", data=inspection_data
    )

    assert update_response.status_code == 302
    with app.app_context():
        inspection = db.session.get(Inspection, inspection_id)
        assert inspection.overall_status == "Critical"
        assert Inspection.query.filter_by(booking_id=assigned_id).count() == 1

    client.post(f"/mechanic/jobs/{assigned_id}/accept")
    client.post(f"/mechanic/jobs/{assigned_id}/start")
    client.post(
        f"/mechanic/jobs/{assigned_id}/complete",
        data={"work_performed": "Completed brake inspection and repair"},
    )
    client.post("/auth/logout")
    login(client, "workshop-customer@example.com", "customer-pass")
    customer_vehicle_id = vehicle_id(app, "MECH-001")

    health_response = client.get(f"/customer/vehicles/{customer_vehicle_id}/health")
    history_response = client.get("/customer/service-history")

    assert health_response.status_code == 200
    assert b"Replace pads at the next visit" in health_response.data
    assert b"Critical" in health_response.data
    assert history_response.status_code == 200
    assert b"Completed brake inspection and repair" in history_response.data
    record_id = get_record_id(app, assigned_id)
    detail_response = client.get(f"/customer/service-history/{record_id}")
    assert b"Replace pads at the next visit" in detail_response.data


def get_record_id(app, booking_id):
    with app.app_context():
        return ServiceRecord.query.filter_by(booking_id=booking_id).one().id