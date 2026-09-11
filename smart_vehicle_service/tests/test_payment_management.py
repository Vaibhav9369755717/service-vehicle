from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from config import Config
from models import Invoice, Notification, Payment, ServiceBooking, User, Vehicle, db


class PaymentTestConfig(Config):
    TESTING = True
    SECRET_KEY = "payment-test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    application = create_app(PaymentTestConfig)
    with application.app_context():
        db.create_all()
        db.session.add_all(
            [
                User(
                    name="Payment Customer",
                    email="payment@example.com",
                    password_hash=generate_password_hash("customer-pass"),
                    role="customer",
                ),
                User(
                    name="Admin User",
                    email="admin@example.com",
                    password_hash=generate_password_hash("admin-pass"),
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


def login_customer(client):
    return client.post(
        "/auth/login",
        data={"email": "payment@example.com", "password": "customer-pass"},
    )


def login_admin(client):
    return client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "admin-pass"},
    )


def create_invoice(app, customer, vehicle, status="pending"):
    booking = ServiceBooking(
        vehicle_id=vehicle.id,
        customer_id=customer.id,
        service_type="Annual service",
        booking_date=date.today(),
        booking_time=time(9, 0),
        status="completed",
    )
    db.session.add(booking)
    db.session.flush()

    invoice = Invoice(
        booking_id=booking.id,
        vehicle_id=vehicle.id,
        customer_id=customer.id,
        invoice_number=f"INV-{booking.id:04d}",
        status=status,
        subtotal=Decimal("200.00"),
        tax=Decimal("20.00"),
        total=Decimal("220.00"),
        due_date=date.today() + timedelta(days=7),
    )
    db.session.add(invoice)
    db.session.commit()
    return invoice


def test_customer_can_view_payment_status_and_history_on_invoice_detail(client, app):
    with app.app_context():
        customer = User.query.filter_by(email="payment@example.com").one()
        vehicle = Vehicle(
            owner=customer,
            registration_number="PMT-001",
            manufacturer="Apex",
            model="Drive",
            mileage=12000,
        )
        db.session.add(vehicle)
        db.session.flush()
        invoice = create_invoice(app, customer, vehicle, status="pending")
        invoice_id = invoice.id
        db.session.add_all(
            [
                Payment(
                    invoice=invoice,
                    customer=customer,
                    payment_reference="REF-PMT-001",
                    transaction_id="TXN-001",
                    amount=Decimal("100.00"),
                    status="pending",
                    payment_method="internal_mock",
                    payment_date=datetime.utcnow(),
                ),
                Payment(
                    invoice=invoice,
                    customer=customer,
                    payment_reference="REF-PMT-002",
                    transaction_id="TXN-002",
                    amount=Decimal("120.00"),
                    status="paid",
                    payment_method="internal_mock",
                    payment_date=datetime.utcnow(),
                ),
            ]
        )
        db.session.commit()

    login_customer(client)
    response = client.get(f"/customer/invoices/{invoice_id}")

    assert response.status_code == 200
    assert b"Payment status" in response.data
    assert b"Payment history" in response.data
    assert b"REF-PMT-002" in response.data
    assert b"Paid" in response.data


def test_customer_can_submit_mock_payment_updates_invoice_and_notifies(client, app):
    with app.app_context():
        customer = User.query.filter_by(email="payment@example.com").one()
        customer_id = customer.id
        vehicle = Vehicle(
            owner=customer,
            registration_number="PMT-002",
            manufacturer="Apex",
            model="Drive",
            mileage=12000,
        )
        db.session.add(vehicle)
        db.session.flush()
        invoice = create_invoice(app, customer, vehicle, status="pending")
        invoice_id = invoice.id
        db.session.commit()

    login_customer(client)
    response = client.post(
        f"/customer/invoices/{invoice_id}/payment",
        data={"status": "paid", "payment_method": "internal_mock"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    with app.app_context():
        invoice_id = invoice_id
        payment = Payment.query.filter_by(invoice_id=invoice_id).order_by(Payment.created_at.desc()).first()
        invoice = db.session.get(Invoice, invoice_id)
        assert payment is not None
        assert payment.status == "paid"
        assert payment.transaction_id
        assert invoice.status == "paid"
        assert Notification.query.filter_by(
            user_id=customer_id,
            invoice_id=invoice_id,
            notification_type="payment_received",
        ).count() == 1


def test_admin_can_record_payment_status_and_validate_input(client, app):
    with app.app_context():
        customer = User.query.filter_by(email="payment@example.com").one()
        vehicle = Vehicle(
            owner=customer,
            registration_number="PMT-003",
            manufacturer="Apex",
            model="Drive",
            mileage=12000,
        )
        db.session.add(vehicle)
        db.session.flush()
        invoice = create_invoice(app, customer, vehicle, status="unpaid")
        invoice_id = invoice.id
        db.session.commit()

    login_admin(client)
    response = client.post(
        f"/admin/invoices/{invoice_id}/payment",
        data={"status": "paid", "payment_method": "internal_mock"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        payment = Payment.query.filter_by(invoice_id=invoice_id).one()
        assert payment.status == "paid"
        assert payment.payment_reference
        assert payment.transaction_id

    invalid_response = client.post(
        f"/admin/invoices/{invoice_id}/payment",
        data={"status": "invalid-status", "payment_method": "internal_mock"},
        follow_redirects=False,
    )
    assert invalid_response.status_code == 302
