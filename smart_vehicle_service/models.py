from datetime import date, datetime, time
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Enum, Numeric


db = SQLAlchemy()


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    specialization = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(30), nullable=False, default="customer")

    customer_payments = db.relationship(
        "Payment",
        foreign_keys="Payment.customer_id",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    vehicles = db.relationship(
        "Vehicle", back_populates="owner", cascade="all, delete-orphan"
    )
    customer_bookings = db.relationship(
        "ServiceBooking",
        foreign_keys="ServiceBooking.customer_id",
        back_populates="customer",
    )
    mechanic_bookings = db.relationship(
        "ServiceBooking",
        foreign_keys="ServiceBooking.mechanic_id",
        back_populates="mechanic",
    )
    notifications = db.relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
    customer_invoices = db.relationship(
        "Invoice",
        foreign_keys="Invoice.customer_id",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    customer_service_records = db.relationship(
        "ServiceRecord",
        foreign_keys="ServiceRecord.customer_id",
        back_populates="customer",
    )
    mechanic_service_records = db.relationship(
        "ServiceRecord",
        foreign_keys="ServiceRecord.mechanic_id",
        back_populates="mechanic",
    )


class Vehicle(TimestampMixin, db.Model):
    __tablename__ = "vehicles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    registration_number = db.Column(db.String(30), nullable=False, unique=True, index=True)
    manufacturer = db.Column(db.String(80), nullable=False)
    model = db.Column(db.String(80), nullable=False)
    variant = db.Column(db.String(80), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    fuel_type = db.Column(db.String(30), nullable=True)
    mileage = db.Column(db.Integer, nullable=False, default=0)
    vin = db.Column(db.String(17), nullable=True, unique=True)
    color = db.Column(db.String(40), nullable=True)

    __table_args__ = (
        CheckConstraint("mileage >= 0", name="check_vehicle_mileage_nonnegative"),
    )

    owner = db.relationship("User", back_populates="vehicles")
    bookings = db.relationship(
        "ServiceBooking", back_populates="vehicle", cascade="all, delete-orphan"
    )
    service_records = db.relationship(
        "ServiceRecord", back_populates="vehicle", cascade="all, delete-orphan"
    )
    inspections = db.relationship(
        "Inspection", back_populates="vehicle", cascade="all, delete-orphan"
    )
    estimates = db.relationship(
        "Estimate", back_populates="vehicle", cascade="all, delete-orphan"
    )
    invoices = db.relationship(
        "Invoice", back_populates="vehicle", cascade="all, delete-orphan"
    )


class ServiceBooking(TimestampMixin, db.Model):
    __tablename__ = "service_bookings"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(
        db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mechanic_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    service_type = db.Column(db.String(100), nullable=False)
    booking_date = db.Column(db.Date, nullable=False)
    booking_time = db.Column(db.Time, nullable=False)
    complaint = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)

    vehicle = db.relationship("Vehicle", back_populates="bookings")
    customer = db.relationship(
        "User", foreign_keys=[customer_id], back_populates="customer_bookings"
    )
    mechanic = db.relationship(
        "User", foreign_keys=[mechanic_id], back_populates="mechanic_bookings"
    )
    service_records = db.relationship(
        "ServiceRecord", back_populates="booking", cascade="all, delete-orphan"
    )
    inspections = db.relationship(
        "Inspection", back_populates="booking", cascade="all, delete-orphan"
    )
    estimates = db.relationship(
        "Estimate", back_populates="booking", cascade="all, delete-orphan"
    )
    invoices = db.relationship(
        "Invoice", back_populates="booking", cascade="all, delete-orphan"
    )


class ServiceRecord(TimestampMixin, db.Model):
    __tablename__ = "service_records"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(
        db.Integer, db.ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id = db.Column(
        db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    mechanic_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    service_type = db.Column(db.String(100), nullable=False, default="General Service")
    service_date = db.Column(db.Date, nullable=False, default=date.today)
    diagnosis = db.Column(db.Text, nullable=True)
    inspection_results = db.Column(db.Text, nullable=True)
    work_performed = db.Column(db.Text, nullable=False)
    mileage = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    labor_charges = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    additional_charges = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_cost = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    booking = db.relationship("ServiceBooking", back_populates="service_records")
    vehicle = db.relationship("Vehicle", back_populates="service_records")
    customer = db.relationship("User", foreign_keys=[customer_id], back_populates="customer_service_records")
    invoice = db.relationship("Invoice", foreign_keys=[invoice_id], back_populates="service_records")
    mechanic = db.relationship("User", foreign_keys=[mechanic_id], back_populates="mechanic_service_records")
    part_usages = db.relationship(
        "PartUsage", back_populates="service_record", cascade="all, delete-orphan"
    )


class Inspection(TimestampMixin, db.Model):
    __tablename__ = "inspections"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(
        db.Integer, db.ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id = db.Column(
        db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    inspector_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overall_status = db.Column(db.String(30), nullable=False, default="pending")
    notes = db.Column(db.Text, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    inspected_at = db.Column(db.DateTime, nullable=True)

    booking = db.relationship("ServiceBooking", back_populates="inspections")
    vehicle = db.relationship("Vehicle", back_populates="inspections")
    inspector = db.relationship("User", foreign_keys=[inspector_id])
    items = db.relationship(
        "InspectionItem", back_populates="inspection", cascade="all, delete-orphan"
    )


class InspectionItem(TimestampMixin, db.Model):
    __tablename__ = "inspection_items"

    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(
        db.Integer, db.ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False
    )
    item_name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending")
    notes = db.Column(db.Text, nullable=True)

    inspection = db.relationship("Inspection", back_populates="items")


class Estimate(TimestampMixin, db.Model):
    __tablename__ = "estimates"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(
        db.Integer, db.ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id = db.Column(
        db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mechanic_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status = db.Column(db.String(30), nullable=False, default="draft")
    subtotal = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    tax = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    booking = db.relationship("ServiceBooking", back_populates="estimates")
    vehicle = db.relationship("Vehicle", back_populates="estimates")
    customer = db.relationship("User", foreign_keys=[customer_id])
    mechanic = db.relationship("User", foreign_keys=[mechanic_id])
    items = db.relationship(
        "EstimateItem", back_populates="estimate", cascade="all, delete-orphan"
    )


class EstimateItem(TimestampMixin, db.Model):
    __tablename__ = "estimate_items"

    id = db.Column(db.Integer, primary_key=True)
    estimate_id = db.Column(
        db.Integer, db.ForeignKey("estimates.id", ondelete="CASCADE"), nullable=False
    )
    part_id = db.Column(
        db.Integer, db.ForeignKey("parts.id", ondelete="SET NULL"), nullable=True
    )
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(Numeric(10, 2), nullable=False, default=Decimal("1.00"))
    unit_price = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    estimate = db.relationship("Estimate", back_populates="items")
    part = db.relationship("Part", back_populates="estimate_items")


class Invoice(TimestampMixin, db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(
        db.Integer, db.ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id = db.Column(
        db.Integer, db.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    estimate_id = db.Column(
        db.Integer, db.ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True
    )
    invoice_number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="unpaid")
    due_date = db.Column(db.Date, nullable=True)
    invoice_date = db.Column(db.Date, nullable=False, default=date.today)
    subtotal = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    tax = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    paid_at = db.Column(db.DateTime, nullable=True)

    booking = db.relationship("ServiceBooking", back_populates="invoices")
    vehicle = db.relationship("Vehicle", back_populates="invoices")
    customer = db.relationship("User", foreign_keys=[customer_id], back_populates="customer_invoices")
    estimate = db.relationship("Estimate")
    service_records = db.relationship(
        "ServiceRecord", back_populates="invoice", foreign_keys="ServiceRecord.invoice_id"
    )
    items = db.relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan"
    )
    payments = db.relationship(
        "Payment", back_populates="invoice", cascade="all, delete-orphan"
    )


class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payment_reference = db.Column(db.String(80), nullable=False, unique=True, index=True)
    transaction_id = db.Column(db.String(80), nullable=False, unique=True, index=True)
    amount = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    status = db.Column(db.String(30), nullable=False, default="pending")
    payment_method = db.Column(db.String(50), nullable=False, default="internal_mock")
    payment_date = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    invoice = db.relationship("Invoice", back_populates="payments")
    customer = db.relationship("User", foreign_keys=[customer_id], back_populates="customer_payments")


class InvoiceItem(TimestampMixin, db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    part_id = db.Column(
        db.Integer, db.ForeignKey("parts.id", ondelete="SET NULL"), nullable=True
    )
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(Numeric(10, 2), nullable=False, default=Decimal("1.00"))
    unit_price = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))

    invoice = db.relationship("Invoice", back_populates="items")
    part = db.relationship("Part", back_populates="invoice_items")


class Part(TimestampMixin, db.Model):
    __tablename__ = "parts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    part_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    category = db.Column(db.String(80), nullable=True, index=True)
    supplier = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    quantity_in_stock = db.Column(db.Integer, nullable=False, default=0)
    minimum_stock = db.Column(db.Integer, nullable=False, default=0)
    purchase_price = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    selling_price = db.Column(Numeric(12, 2), nullable=True)
    unit_price = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    reorder_level = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("quantity_in_stock >= 0", name="check_part_stock_nonnegative"),
        CheckConstraint("minimum_stock >= 0", name="check_part_minimum_stock_nonnegative"),
        CheckConstraint("purchase_price >= 0", name="check_part_purchase_price_nonnegative"),
        CheckConstraint("selling_price IS NULL OR selling_price >= 0", name="check_part_selling_price_nonnegative"),
        CheckConstraint("reorder_level >= 0", name="check_part_reorder_nonnegative"),
    )

    estimate_items = db.relationship("EstimateItem", back_populates="part")
    invoice_items = db.relationship("InvoiceItem", back_populates="part")
    usages = db.relationship("PartUsage", back_populates="part")


class PartUsage(TimestampMixin, db.Model):
    __tablename__ = "part_usages"

    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(
        db.Integer, db.ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False
    )
    service_record_id = db.Column(
        db.Integer, db.ForeignKey("service_records.id", ondelete="CASCADE"), nullable=False
    )
    quantity = db.Column(Numeric(10, 2), nullable=False, default=Decimal("1.00"))
    unit_cost = db.Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    used_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    part = db.relationship("Part", back_populates="usages")
    service_record = db.relationship("ServiceRecord", back_populates="part_usages")


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    booking_id = db.Column(
        db.Integer, db.ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=True
    )
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True
    )
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(40), nullable=False, default="info")
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="notifications")
    booking = db.relationship("ServiceBooking")
    invoice = db.relationship("Invoice")