from datetime import date, datetime, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models import (
    Inspection,
    Invoice,
    Notification,
    PartUsage,
    ServiceBooking,
    ServiceRecord,
    Vehicle,
    db,
)
from routes.decorators import role_required


customer_bp = Blueprint("customer", __name__)
ACTIVE_STATUSES = {
    "active",
    "assigned",
    "checked_in",
    "in_progress",
    "vehicle received",
    "inspection",
    "work in progress",
    "quality check",
}
UPCOMING_EXCLUDED_STATUSES = {"cancelled", "completed", "closed"}
COMPLETED_SERVICE_STATUSES = {"completed", "closed"}
HEALTH_COMPONENTS = {
    "Engine": ("engine", "motor"),
    "Brakes": ("brake",),
    "Tyres": ("tire", "tyre", "wheel"),
    "Battery": ("battery",),
    "Suspension": ("suspension", "shock", "strut"),
    "Oil": ("oil", "lubrication", "filter"),
    "Lights": ("light", "lamp", "headlamp"),
}
HEALTH_STATUS_RANK = {"Not assessed": 0, "Good": 1, "Needs Attention": 2, "Critical": 3}
VEHICLE_FORM_FIELDS = (
    "registration_number",
    "manufacturer",
    "model",
    "variant",
    "year",
    "fuel_type",
    "mileage",
    "vin",
    "color",
)
BOOKING_STATUSES = (
    "Requested",
    "Confirmed",
    "Vehicle Received",
    "Inspection",
    "Work In Progress",
    "Quality Check",
    "Ready for Pickup",
    "Completed",
)
SERVICE_TYPES = (
    "General Service",
    "Oil Change",
    "Brake Service",
    "AC Service",
    "Battery Service",
    "Tire Service",
    "Engine Inspection",
    "Full Vehicle Inspection",
    "Custom Repair",
)
PICKUP_OPTIONS = (
    "Customer drop-off",
    "Pickup and drop-off",
    "Pickup from customer",
)
BOOKING_FORM_FIELDS = (
    "vehicle_id",
    "service_type",
    "preferred_date",
    "preferred_time",
    "complaint",
    "additional_notes",
    "pickup_option",
)
PICKUP_NOTE_PREFIX = "Pickup/drop-off option: "


@customer_bp.get("/customer/dashboard")
@role_required("customer")
def customer_dashboard():
    customer_id = current_user.id

    vehicles = (
        Vehicle.query.filter(Vehicle.user_id == customer_id)
        .order_by(Vehicle.created_at.desc())
        .all()
    )
    vehicle_ids = [vehicle.id for vehicle in vehicles]

    customer_bookings = (
        ServiceBooking.query.join(Vehicle, ServiceBooking.vehicle_id == Vehicle.id)
        .filter(
            ServiceBooking.customer_id == customer_id,
            Vehicle.user_id == customer_id,
        )
        .options(joinedload(ServiceBooking.vehicle))
    )
    upcoming_service = (
        customer_bookings.filter(
            ServiceBooking.booking_date >= date.today(),
            ~func.lower(ServiceBooking.status).in_(UPCOMING_EXCLUDED_STATUSES),
        )
        .order_by(ServiceBooking.booking_date, ServiceBooking.booking_time)
        .first()
    )
    active_service_count = customer_bookings.filter(
        func.lower(ServiceBooking.status).in_(ACTIVE_STATUSES)
    ).count()
    recent_bookings = customer_bookings.order_by(
        ServiceBooking.created_at.desc()
    ).limit(5).all()

    service_history = []
    if vehicle_ids:
        service_history = (
            ServiceRecord.query.filter(ServiceRecord.vehicle_id.in_(vehicle_ids))
            .join(Vehicle, ServiceRecord.vehicle_id == Vehicle.id)
            .filter(Vehicle.user_id == customer_id)
            .options(joinedload(ServiceRecord.vehicle))
            .order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc())
            .limit(5)
            .all()
        )

    recent_invoices = (
        Invoice.query.filter(Invoice.customer_id == customer_id)
        .order_by(Invoice.created_at.desc())
        .limit(4)
        .all()
    )
    notifications = (
        Notification.query.filter(Notification.user_id == customer_id)
        .order_by(Notification.is_read, Notification.created_at.desc())
        .limit(5)
        .all()
    )
    unread_notification_count = Notification.query.filter_by(
        user_id=customer_id, is_read=False
    ).count()

    inspection_statuses = []
    if vehicle_ids:
        inspection_statuses = [
            status
            for (status,) in db.session.query(Inspection.overall_status)
            .join(Vehicle, Inspection.vehicle_id == Vehicle.id)
            .filter(Vehicle.user_id == customer_id)
            .all()
            if status
        ]
    vehicle_health = get_vehicle_health(vehicles, inspection_statuses)
    maintenance_reminders = build_maintenance_reminders(vehicles)

    return render_template(
        "customer/dashboard.html",
        page_title="Customer Dashboard",
        vehicles=vehicles,
        upcoming_service=upcoming_service,
        active_service_count=active_service_count,
        recent_bookings=recent_bookings,
        service_history=service_history,
        notifications=notifications,
        unread_notification_count=unread_notification_count,
        recent_invoices=recent_invoices,
        vehicle_health=vehicle_health,
        maintenance_reminders=maintenance_reminders,
    )


@customer_bp.get("/customer/notifications")
@role_required("customer")
def customer_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.is_read, Notification.created_at.desc()
    ).all()
    return render_template(
        "customer/notifications.html",
        page_title="Notifications",
        notifications=notifications,
    )


@customer_bp.get("/customer/service-history")
@role_required("customer")
def customer_service_history():
    vehicles = Vehicle.query.filter_by(user_id=current_user.id).order_by(
        Vehicle.manufacturer, Vehicle.model
    ).all()
    records_query = customer_service_history_query()

    vehicle_id = parse_positive_int(request.args.get("vehicle_id"))
    if vehicle_id and any(vehicle.id == vehicle_id for vehicle in vehicles):
        records_query = records_query.filter(ServiceRecord.vehicle_id == vehicle_id)
    else:
        vehicle_id = None

    service_type = request.args.get("service_type", "").strip()
    if service_type:
        records_query = records_query.filter(ServiceBooking.service_type == service_type)

    search = request.args.get("q", "").strip()
    if search:
        search_term = f"%{search}%"
        records_query = records_query.filter(
            or_(
                ServiceBooking.service_type.ilike(search_term),
                ServiceRecord.work_performed.ilike(search_term),
                ServiceRecord.diagnosis.ilike(search_term),
            )
        )

    date_from = parse_date(request.args.get("date_from"))
    date_to = parse_date(request.args.get("date_to"))
    if date_from:
        records_query = records_query.filter(ServiceRecord.service_date >= date_from)
    if date_to:
        records_query = records_query.filter(ServiceRecord.service_date <= date_to)

    records = records_query.order_by(
        ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc()
    ).all()
    booking_ids = [record.booking_id for record in records]
    invoices = (
        Invoice.query.filter(
            Invoice.customer_id == current_user.id,
            Invoice.booking_id.in_(booking_ids),
        )
        .order_by(Invoice.created_at.desc())
        .all()
        if booking_ids
        else []
    )


    latest_invoices = {}
    for invoice in invoices:
        latest_invoices.setdefault(invoice.booking_id, invoice)
    service_costs = {
        record.id: latest_invoices.get(record.booking_id).total
        if record.booking_id in latest_invoices
        else 0
        for record in records
    }
    service_types = [
        service_type
        for (service_type,) in customer_service_history_query()
        .with_entities(ServiceBooking.service_type)
        .distinct()
        .order_by(ServiceBooking.service_type)
        .all()
    ]
    return render_template(
        "customer/service_history.html",
        page_title="Service History",
        records=records,
        service_costs=service_costs,
        vehicles=vehicles,
        service_types=service_types,
        filters={
            "vehicle_id": vehicle_id,
            "service_type": service_type,
            "q": search,
            "date_from": request.args.get("date_from", ""),
            "date_to": request.args.get("date_to", ""),
        },
    )


@customer_bp.get("/customer/vehicles/<int:vehicle_id>/health")
@role_required("customer")
def vehicle_health(vehicle_id):
    vehicle = get_owned_vehicle(vehicle_id)
    health = build_vehicle_health(vehicle)
    return render_template(
        "customer/vehicle_health.html",
        page_title="Vehicle Health",
        vehicle=vehicle,
        health=health,
    )


@customer_bp.get("/customer/service-history/<int:record_id>")
@role_required("customer")
def service_history_detail(record_id):
    record = get_owned_completed_service_record(record_id)
    invoice = (
        Invoice.query.filter_by(
            booking_id=record.booking_id,
            customer_id=current_user.id,
        )
        .order_by(Invoice.created_at.desc())
        .first()
    )
    inspection = Inspection.query.filter_by(booking_id=record.booking_id).order_by(
        Inspection.created_at.desc()
    ).first()
    return render_template(
        "customer/service_history_detail.html",
        page_title="Service Details",
        record=record,
        invoice=invoice,
        total_cost=invoice.total if invoice else 0,
        inspection=inspection,
    )


@customer_bp.get("/customer/invoices")
@role_required("customer")
def customer_invoices():
    invoices = (
        Invoice.query.filter_by(customer_id=current_user.id)
        .options(joinedload(Invoice.vehicle), joinedload(Invoice.booking))
        .order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc())
        .all()
    )
    return render_template(
        "customer/invoices.html",
        page_title="Invoices",
        invoices=invoices,
    )


@customer_bp.get("/customer/invoices/<int:invoice_id>")
@role_required("customer")
def customer_invoice_detail(invoice_id):
    invoice = (
        Invoice.query.filter_by(id=invoice_id, customer_id=current_user.id)
        .options(joinedload(Invoice.vehicle), joinedload(Invoice.booking), joinedload(Invoice.customer))
        .first_or_404()
    )
    service_record = ServiceRecord.query.filter_by(booking_id=invoice.booking_id).order_by(
        ServiceRecord.created_at.desc()
    ).first()
    return render_template(
        "customer/invoice_detail.html",
        page_title=f"Invoice {invoice.invoice_number}",
        invoice=invoice,
        service_record=service_record,
    )


@customer_bp.post("/customer/notifications/<int:notification_id>/read")
@role_required("customer")
def mark_notification_read(notification_id):
    notification = get_owned_notification(notification_id)
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("customer.customer_notifications"))


@customer_bp.post("/customer/notifications/read-all")
@role_required("customer")
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {Notification.is_read: True, Notification.read_at: datetime.utcnow()},
        synchronize_session=False,
    )
    db.session.commit()
    return redirect(url_for("customer.customer_notifications"))


@customer_bp.get("/customer/notifications/<int:notification_id>")
@role_required("customer")
def notification_details(notification_id):
    notification = get_owned_notification(notification_id)
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    db.session.commit()
    if notification.booking and notification.booking.customer_id == current_user.id:
        return redirect(url_for("customer.booking_details", booking_id=notification.booking.id))
    if notification.invoice and notification.invoice.customer_id == current_user.id:
        return redirect(url_for("customer.booking_details", booking_id=notification.invoice.booking_id))
    return redirect(url_for("customer.customer_notifications"))


def get_vehicle_health(vehicles, inspection_statuses):
    if not vehicles:
        return {"label": "No vehicles", "detail": "Add a vehicle to begin", "tone": "muted"}
    normalized_statuses = {status.lower().replace(" ", "_") for status in inspection_statuses}
    if not normalized_statuses:
        return {"label": "Not assessed", "detail": "Schedule an inspection", "tone": "muted"}
    if normalized_statuses.intersection({"critical", "fail", "needs_attention"}):
        return {"label": "Needs attention", "detail": "Review inspection results", "tone": "danger"}
    if normalized_statuses.intersection({"warning", "monitor"}):
        return {"label": "Monitor", "detail": "A checkup is recommended", "tone": "warning"}
    return {"label": "Good", "detail": "Your vehicles are looking good", "tone": "success"}


def build_vehicle_health(vehicle):
    completed_records = (
        ServiceRecord.query.join(ServiceBooking, ServiceRecord.booking_id == ServiceBooking.id)
        .filter(
            ServiceRecord.vehicle_id == vehicle.id,
            ServiceBooking.customer_id == current_user.id,
            func.lower(ServiceBooking.status).in_(COMPLETED_SERVICE_STATUSES),
        )
        .options(joinedload(ServiceRecord.booking))
        .order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc())
        .all()
    )
    inspections = (
        Inspection.query.filter_by(vehicle_id=vehicle.id)
        .options(joinedload(Inspection.items))
        .order_by(Inspection.inspected_at.desc(), Inspection.created_at.desc())
        .limit(5)
        .all()
    )
    latest_record = completed_records[0] if completed_records else None
    latest_inspection = inspections[0] if inspections else None
    evidence = " ".join(
        [
            (latest_record.booking.service_type if latest_record else "") or "",
            (latest_record.work_performed if latest_record else "") or "",
            (latest_record.diagnosis if latest_record else "") or "",
        ]
    ).lower()
    indicators = []
    for component, keywords in HEALTH_COMPONENTS.items():
        status = inspection_component_status(inspections, keywords)
        if status == "Not assessed" and any(keyword in evidence for keyword in keywords):
            status = "Good"
        indicators.append({"name": component, "status": status, "tone": health_tone(status)})

    overall_status = max(
        (indicator["status"] for indicator in indicators),
        key=lambda status: HEALTH_STATUS_RANK[status],
        default="Not assessed",
    )
    last_service = latest_record.service_date if latest_record else None
    next_service_date = last_service + timedelta(days=180) if last_service else None
    upcoming_booking = (
        ServiceBooking.query.filter(
            ServiceBooking.vehicle_id == vehicle.id,
            ServiceBooking.customer_id == current_user.id,
            ServiceBooking.booking_date >= date.today(),
            ~func.lower(ServiceBooking.status).in_(UPCOMING_EXCLUDED_STATUSES),
        )
        .order_by(ServiceBooking.booking_date, ServiceBooking.booking_time)
        .first()
    )
    reminders = []
    if upcoming_booking:
        reminders.append({
            "title": upcoming_booking.service_type,
            "detail": "Scheduled service",
            "date": upcoming_booking.booking_date,
            "tone": "info",
        })
    elif next_service_date and next_service_date <= date.today() + timedelta(days=30):
        reminders.append({
            "title": "Routine service recommended",
            "detail": "Six-month service interval",
            "date": next_service_date,
            "tone": "warning",
        })
    if latest_inspection and normalize_health_status(latest_inspection.overall_status) in {"Needs Attention", "Critical"}:
        reminders.append({
            "title": "Follow up inspection results",
            "detail": latest_inspection.overall_status,
            "date": latest_inspection.inspected_at.date() if latest_inspection.inspected_at else latest_inspection.created_at.date(),
            "tone": "danger",
        })
    return {
        "overall_status": overall_status,
        "overall_tone": health_tone(overall_status),
        "indicators": indicators,
        "last_service": latest_record,
        "current_mileage": vehicle.mileage,
        "next_service_date": next_service_date,
        "maintenance_status": "Up to date" if not reminders else "Maintenance due",
        "inspections": inspections,
        "service_history": completed_records,
        "reminders": reminders,
    }


def build_maintenance_reminders(vehicles):
    reminders = []
    for vehicle in vehicles:
        health = build_vehicle_health(vehicle)
        for reminder in health["reminders"]:
            reminders.append({"vehicle": vehicle, **reminder})
    return sorted(reminders, key=lambda reminder: reminder["date"])


def inspection_component_status(inspections, keywords):
    for inspection in inspections:
        for item in inspection.items:
            if any(keyword in item.item_name.lower() for keyword in keywords):
                return normalize_health_status(item.status)
    return "Not assessed"


def normalize_health_status(status):
    normalized = (status or "").lower().replace("_", " ")
    if normalized in {"critical", "fail", "failed", "danger"}:
        return "Critical"
    if normalized in {"warning", "needs attention", "needs_attention", "monitor"}:
        return "Needs Attention"
    if normalized in {"good", "pass", "passed", "ok", "normal", "complete", "completed"}:
        return "Good"
    return "Not assessed"


def health_tone(status):
    return {"Good": "success", "Needs Attention": "warning", "Critical": "danger"}.get(status, "muted")


def customer_service_history_query():
    return (
        ServiceRecord.query
        .join(ServiceBooking, ServiceRecord.booking_id == ServiceBooking.id)
        .join(Vehicle, ServiceRecord.vehicle_id == Vehicle.id)
        .filter(
            ServiceBooking.customer_id == current_user.id,
            Vehicle.user_id == current_user.id,
            func.lower(ServiceBooking.status).in_(COMPLETED_SERVICE_STATUSES),
        )
        .options(
            joinedload(ServiceRecord.vehicle),
            joinedload(ServiceRecord.booking),
            joinedload(ServiceRecord.mechanic),
            joinedload(ServiceRecord.part_usages).joinedload(PartUsage.part),
        )
    )


def get_owned_completed_service_record(record_id):
    return customer_service_history_query().filter(
        ServiceRecord.id == record_id
    ).first_or_404()


def parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@customer_bp.get("/customer/vehicles")
@role_required("customer")
def customer_vehicles():
    customer_id = current_user.id
    vehicles = (
        Vehicle.query.filter(Vehicle.user_id == customer_id)
        .order_by(Vehicle.created_at.desc())
        .all()
    )
    vehicle_ids = [vehicle.id for vehicle in vehicles]
    last_services = {}
    if vehicle_ids:
        service_records = (
            ServiceRecord.query.filter(ServiceRecord.vehicle_id.in_(vehicle_ids))
            .join(Vehicle, ServiceRecord.vehicle_id == Vehicle.id)
            .filter(Vehicle.user_id == customer_id)
            .order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc())
            .all()
        )
        for record in service_records:
            last_services.setdefault(record.vehicle_id, record)

    return render_template(
        "customer/vehicles.html",
        page_title="My Vehicles",
        vehicles=vehicles,
        last_services=last_services,
    )


@customer_bp.route("/customer/vehicles/add", methods=["GET", "POST"])
@role_required("customer")
def add_vehicle():
    form = vehicle_form_data()
    errors = []
    if request.method == "POST":
        form = vehicle_form_data(request.form)
        errors, values = validate_vehicle_form(form)
        if not errors:
            vehicle = Vehicle(user_id=current_user.id, **values)
            db.session.add(vehicle)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("A vehicle with that registration number or VIN already exists.")
            else:
                flash("Vehicle added successfully.", "success")
                return redirect(url_for("customer.customer_vehicles"))
    return render_template(
        "customer/vehicle_form.html",
        page_title="Add Vehicle",
        form=form,
        errors=errors,
        current_year=date.today().year + 1,
        form_heading="Add your vehicle",
        form_intro="Keep your vehicle details ready for every service visit.",
        submit_label="Add vehicle",
    )


@customer_bp.get("/customer/vehicles/<int:vehicle_id>")
@role_required("customer")
def vehicle_details(vehicle_id):
    vehicle = get_owned_vehicle(vehicle_id)
    service_history = (
        ServiceRecord.query.filter_by(vehicle_id=vehicle.id)
        .order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc())
        .all()
    )
    upcoming_service = (
        ServiceBooking.query.filter(
            ServiceBooking.vehicle_id == vehicle.id,
            ServiceBooking.customer_id == current_user.id,
            ServiceBooking.booking_date >= date.today(),
            ~func.lower(ServiceBooking.status).in_(UPCOMING_EXCLUDED_STATUSES),
        )
        .order_by(ServiceBooking.booking_date, ServiceBooking.booking_time)
        .first()
    )
    total_service_cost = (
        db.session.query(func.coalesce(func.sum(Invoice.total), 0))
        .filter(
            Invoice.vehicle_id == vehicle.id,
            Invoice.customer_id == current_user.id,
        )
        .scalar()
    )
    return render_template(
        "customer/vehicle_details.html",
        page_title=f"{vehicle.manufacturer} {vehicle.model}",
        vehicle=vehicle,
        service_history=service_history,
        upcoming_service=upcoming_service,
        total_service_cost=total_service_cost,
    )


@customer_bp.route("/customer/vehicles/<int:vehicle_id>/edit", methods=["GET", "POST"])
@role_required("customer")
def edit_vehicle(vehicle_id):
    vehicle = get_owned_vehicle(vehicle_id)
    form = vehicle_form_data(vehicle)
    errors = []
    if request.method == "POST":
        form = vehicle_form_data(request.form)
        errors, values = validate_vehicle_form(form, vehicle_id=vehicle.id)
        if not errors:
            for field, value in values.items():
                setattr(vehicle, field, value)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("A vehicle with that registration number or VIN already exists.")
            else:
                flash("Vehicle details updated successfully.", "success")
                return redirect(url_for("customer.vehicle_details", vehicle_id=vehicle.id))
    return render_template(
        "customer/vehicle_form.html",
        page_title="Edit Vehicle",
        form=form,
        errors=errors,
        current_year=date.today().year + 1,
        form_heading="Edit vehicle details",
        form_intro="Keep your vehicle information accurate and up to date.",
        submit_label="Save changes",
        vehicle=vehicle,
    )


@customer_bp.post("/customer/vehicles/<int:vehicle_id>/delete")
@role_required("customer")
def delete_vehicle(vehicle_id):
    vehicle = get_owned_vehicle(vehicle_id)
    db.session.delete(vehicle)
    db.session.commit()
    flash("Vehicle deleted successfully.", "success")
    return redirect(url_for("customer.customer_vehicles"))


def get_owned_vehicle(vehicle_id):
    return Vehicle.query.filter(
        Vehicle.id == vehicle_id,
        Vehicle.user_id == current_user.id,
    ).first_or_404()


def get_owned_notification(notification_id):
    return Notification.query.filter_by(
        id=notification_id, user_id=current_user.id
    ).first_or_404()


def vehicle_form_data(source=None):
    if source is None:
        return {field: "" for field in VEHICLE_FORM_FIELDS}
    if hasattr(source, "get"):
        return {field: source.get(field, "").strip() for field in VEHICLE_FORM_FIELDS}
    return {
        field: "" if getattr(source, field) is None else str(getattr(source, field))
        for field in VEHICLE_FORM_FIELDS
    }


def validate_vehicle_form(form, vehicle_id=None):
    errors = []
    values = {}
    required_fields = {
        "registration_number": "Registration number",
        "manufacturer": "Manufacturer",
        "model": "Model",
        "year": "Manufacturing year",
        "fuel_type": "Fuel type",
        "mileage": "Current mileage",
    }
    for field, label in required_fields.items():
        if not form.get(field):
            errors.append(f"{label} is required.")

    registration_number = form.get("registration_number", "").upper()
    if registration_number and len(registration_number) > 30:
        errors.append("Registration number must be 30 characters or fewer.")
    if registration_number:
        registration_query = Vehicle.query.filter(
            func.upper(Vehicle.registration_number) == registration_number
        )
        if vehicle_id is not None:
            registration_query = registration_query.filter(Vehicle.id != vehicle_id)
        if registration_query.first():
            errors.append("That registration number is already in use.")

    year = None
    if form.get("year"):
        try:
            year = int(form["year"])
        except ValueError:
            errors.append("Manufacturing year must be a valid number.")
        else:
            if year < 1886 or year > date.today().year + 1:
                errors.append("Manufacturing year must be between 1886 and next year.")

    mileage = None
    if form.get("mileage"):
        try:
            mileage = int(form["mileage"])
        except ValueError:
            errors.append("Mileage must be a whole number.")
        else:
            if mileage < 0:
                errors.append("Mileage cannot be negative.")

    vin = form.get("vin", "").upper()
    if vin and len(vin) != 17:
        errors.append("VIN/chassis number must be 17 characters when provided.")
    if vin:
        vin_query = Vehicle.query.filter(func.upper(Vehicle.vin) == vin)
        if vehicle_id is not None:
            vin_query = vin_query.filter(Vehicle.id != vehicle_id)
        if vin_query.first():
            errors.append("That VIN/chassis number is already in use.")

    if errors:
        return errors, values
    values = {
        "registration_number": registration_number,
        "manufacturer": form["manufacturer"],
        "model": form["model"],
        "variant": form.get("variant") or None,
        "year": year,
        "fuel_type": form["fuel_type"],
        "mileage": mileage,
        "vin": vin or None,
        "color": form.get("color") or None,
    }
    return errors, values


@customer_bp.route("/customer/book-service", methods=["GET", "POST"])
@role_required("customer")
def book_service():
    vehicles = (
        Vehicle.query.filter_by(user_id=current_user.id)
        .order_by(Vehicle.registration_number)
        .all()
    )
    form = booking_form_data()
    errors = []
    if request.method == "POST":
        form = booking_form_data(request.form)
        errors, values = validate_booking_form(form, vehicles)
        if not errors:
            booking = ServiceBooking(
                vehicle_id=values["vehicle_id"],
                customer_id=current_user.id,
                service_type=values["service_type"],
                booking_date=values["booking_date"],
                booking_time=values["booking_time"],
                complaint=values["complaint"],
                notes=values["notes"],
                status="Requested",
            )
            db.session.add(booking)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("This booking could not be saved. Please try again.")
            else:
                flash("Service booking requested successfully.", "success")
                return redirect(url_for("customer.booking_details", booking_id=booking.id))
    return render_template(
        "customer/book_service.html",
        page_title="Book Service",
        vehicles=vehicles,
        form=form,
        errors=errors,
        service_types=SERVICE_TYPES,
        pickup_options=PICKUP_OPTIONS,
        minimum_date=date.today().isoformat(),
    )


@customer_bp.get("/customer/bookings")
@role_required("customer")
def customer_bookings():
    bookings = (
        ServiceBooking.query.join(Vehicle, ServiceBooking.vehicle_id == Vehicle.id)
        .filter(
            ServiceBooking.customer_id == current_user.id,
            Vehicle.user_id == current_user.id,
        )
        .options(joinedload(ServiceBooking.vehicle))
        .order_by(ServiceBooking.booking_date.desc(), ServiceBooking.booking_time.desc())
        .all()
    )
    return render_template(
        "customer/bookings.html",
        page_title="My Bookings",
        bookings=bookings,
    )


@customer_bp.get("/customer/bookings/<int:booking_id>")
@role_required("customer")
def booking_details(booking_id):
    booking = get_owned_booking(booking_id)
    pickup_option, additional_notes = split_booking_notes(booking.notes)
    return render_template(
        "customer/booking_detail.html",
        page_title="Booking Details",
        booking=booking,
        pickup_option=pickup_option,
        additional_notes=additional_notes,
        timeline=booking_timeline(booking.status),
    )


def get_owned_booking(booking_id):
    return (
        ServiceBooking.query.join(Vehicle, ServiceBooking.vehicle_id == Vehicle.id)
        .filter(
            ServiceBooking.id == booking_id,
            ServiceBooking.customer_id == current_user.id,
            Vehicle.user_id == current_user.id,
        )
        .options(joinedload(ServiceBooking.vehicle))
        .first_or_404()
    )


def booking_form_data(source=None):
    if source is None:
        return {field: "" for field in BOOKING_FORM_FIELDS}
    return {
        field: source.get(field, "").strip()
        for field in BOOKING_FORM_FIELDS
    }


def validate_booking_form(form, vehicles):
    errors = []
    values = {}
    required_fields = {
        "vehicle_id": "Vehicle",
        "service_type": "Service type",
        "preferred_date": "Preferred date",
        "preferred_time": "Preferred time",
        "complaint": "Customer complaint",
        "pickup_option": "Pickup/drop-off option",
    }
    for field, label in required_fields.items():
        if not form.get(field):
            errors.append(f"{label} is required.")

    vehicle = None
    try:
        vehicle_id = int(form.get("vehicle_id", ""))
    except (TypeError, ValueError):
        vehicle_id = None
    if vehicle_id is not None:
        vehicle = next((item for item in vehicles if item.id == vehicle_id), None)
        if vehicle is None:
            errors.append("Please select one of your vehicles.")

    if form.get("service_type") and form["service_type"] not in SERVICE_TYPES:
        errors.append("Please select a valid service type.")
    if form.get("pickup_option") and form["pickup_option"] not in PICKUP_OPTIONS:
        errors.append("Please select a valid pickup/drop-off option.")

    booking_date = None
    if form.get("preferred_date"):
        try:
            booking_date = datetime.strptime(form["preferred_date"], "%Y-%m-%d").date()
        except ValueError:
            errors.append("Preferred date must be a valid date.")
        else:
            if booking_date < date.today():
                errors.append("Preferred date cannot be in the past.")

    booking_time = None
    if form.get("preferred_time"):
        try:
            booking_time = datetime.strptime(form["preferred_time"], "%H:%M").time()
        except ValueError:
            errors.append("Preferred time must be a valid time.")

    if vehicle and booking_date and booking_time:
        conflict = (
            ServiceBooking.query.filter(
                ServiceBooking.vehicle_id == vehicle.id,
                ServiceBooking.booking_date == booking_date,
                ServiceBooking.booking_time == booking_time,
                ~func.lower(ServiceBooking.status).in_({"cancelled", "completed"}),
            ).first()
        )
        if conflict:
            errors.append("This vehicle already has a booking at that date and time.")

    if errors:
        return errors, values
    values = {
        "vehicle_id": vehicle.id,
        "service_type": form["service_type"],
        "booking_date": booking_date,
        "booking_time": booking_time,
        "complaint": form["complaint"],
        "notes": compose_booking_notes(
            form["pickup_option"], form.get("additional_notes", "")
        ),
    }
    return errors, values


def compose_booking_notes(pickup_option, additional_notes):
    pickup_line = f"{PICKUP_NOTE_PREFIX}{pickup_option}"
    return f"{pickup_line}\n{additional_notes}" if additional_notes else pickup_line


def split_booking_notes(notes):
    if not notes:
        return "Not specified", ""
    first_line, separator, remaining = notes.partition("\n")
    if first_line.startswith(PICKUP_NOTE_PREFIX):
        return first_line[len(PICKUP_NOTE_PREFIX):], remaining if separator else ""
    return "Not specified", notes


def booking_timeline(status):
    current_status = status or "Requested"
    statuses = list(BOOKING_STATUSES)
    if current_status not in statuses:
        statuses.append(current_status)
    current_index = statuses.index(current_status)
    return [
        {
            "label": label,
            "complete": index <= current_index,
            "current": index == current_index,
        }
        for index, label in enumerate(statuses)
    ]