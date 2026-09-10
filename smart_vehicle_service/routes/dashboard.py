from calendar import month_abbr
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy import extract, func, or_
from sqlalchemy.orm import joinedload

from models import (
    Inspection,
    InspectionItem,
    Invoice,
    InvoiceItem,
    Notification,
    Part,
    PartUsage,
    ServiceBooking,
    ServiceRecord,
    User,
    Vehicle,
    db,
)
from routes.decorators import role_required

dashboard_bp = Blueprint("dashboard", __name__)

MECHANIC_PENDING_STATUSES = {"requested", "pending", "confirmed", "assigned"}
MECHANIC_ACCEPTED_STATUSES = {"accepted"}
MECHANIC_PROGRESS_STATUSES = {"in progress", "work in progress"}
MECHANIC_COMPLETED_STATUSES = {"completed", "closed"}
INSPECTION_CATEGORIES = (
    ("Engine", "engine"),
    ("Brakes", "brakes"),
    ("Tyres", "tyres"),
    ("Battery", "battery"),
    ("Suspension", "suspension"),
    ("Lights", "lights"),
    ("Engine oil", "engine_oil"),
    ("Coolant", "coolant"),
    ("AC", "ac"),
    ("Overall condition", "overall_condition"),
)
INSPECTION_STATUSES = {"Good", "Needs Attention", "Critical"}
INSPECTION_STATUS_RANK = {"Good": 1, "Needs Attention": 2, "Critical": 3}
ADMIN_BOOKING_STATUSES = (
    "Requested",
    "Approved",
    "Assigned",
    "Accepted",
    "In Progress",
    "Completed",
    "Rejected",
    "Cancelled",
)


@dashboard_bp.get("/mechanic/dashboard")
@role_required("mechanic", "admin")
def mechanic_dashboard():
    jobs = mechanic_jobs_query().order_by(
        ServiceBooking.booking_date, ServiceBooking.booking_time
    ).all()
    inspections = mechanic_inspections_query().order_by(
        Inspection.created_at.desc()
    ).limit(6).all()
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.is_read, Notification.created_at.desc()
    ).limit(6).all()
    return render_template(
        "mechanic/dashboard.html",
        page_title="Mechanic Dashboard",
        jobs=jobs,
        today_jobs=[job for job in jobs if job.booking_date == date.today()],
        inspections=inspections,
        notifications=notifications,
        stats=build_mechanic_stats(jobs),
        is_admin=current_user.role == "admin",
    )


@dashboard_bp.get("/mechanic/jobs")
@role_required("mechanic", "admin")
def mechanic_jobs():
    jobs = mechanic_jobs_query().order_by(
        ServiceBooking.booking_date.desc(), ServiceBooking.booking_time.desc()
    ).all()
    return render_template(
        "mechanic/jobs.html",
        page_title="Assigned Jobs",
        jobs=jobs,
        is_admin=current_user.role == "admin",
    )


@dashboard_bp.get("/mechanic/jobs/<int:booking_id>")
@role_required("mechanic", "admin")
def mechanic_job_detail(booking_id):
    job = get_accessible_job(booking_id)
    inspection = Inspection.query.filter_by(booking_id=job.id).order_by(
        Inspection.created_at.desc()
    ).first()
    service_record = ServiceRecord.query.filter_by(booking_id=job.id).order_by(
        ServiceRecord.created_at.desc()
    ).first()
    available_parts = Part.query.filter(Part.quantity_in_stock > 0).order_by(Part.name).all()
    return render_template(
        "mechanic/job_detail.html",
        page_title="Job Details",
        job=job,
        inspection=inspection,
        service_record=service_record,
        available_parts=available_parts,
    )


@dashboard_bp.route("/mechanic/jobs/<int:booking_id>/inspection", methods=["GET", "POST"])
@role_required("mechanic", "admin")
def mechanic_job_inspection(booking_id):
    job = get_accessible_job(booking_id)
    inspection = Inspection.query.filter_by(booking_id=job.id).order_by(
        Inspection.created_at.desc()
    ).first()
    values = inspection_form_values(inspection)
    errors = []
    if request.method == "POST":
        values = inspection_form_values_from_request(request.form)
        errors = validate_inspection_values(values)
        if not errors:
            if inspection is None:
                inspection = Inspection(
                    booking_id=job.id,
                    vehicle_id=job.vehicle_id,
                    inspector_id=current_user.id,
                )
                db.session.add(inspection)
                db.session.flush()
            inspection.overall_status = overall_inspection_status(values)
            inspection.notes = values["notes"] or None
            inspection.recommendations = values["recommendations"] or None
            inspection.inspector_id = current_user.id
            inspection.inspected_at = datetime.utcnow()
            inspection.items.clear()
            for label, field_name in INSPECTION_CATEGORIES:
                inspection.items.append(
                    InspectionItem(
                        item_name=label,
                        status=values[field_name],
                        notes=values[f"{field_name}_notes"] or None,
                    )
                )
            db.session.commit()
            flash("Vehicle inspection saved.", "success")
            return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))
    return render_template(
        "mechanic/inspection_form.html",
        page_title="Vehicle Inspection",
        job=job,
        inspection=inspection,
        categories=INSPECTION_CATEGORIES,
        values=values,
        errors=errors,
    )


@dashboard_bp.post("/mechanic/jobs/<int:booking_id>/accept")
@role_required("mechanic", "admin")
def accept_mechanic_job(booking_id):
    job = get_accessible_job(booking_id)
    if normalize_status(job.status) not in MECHANIC_PENDING_STATUSES:
        flash("Only pending jobs can be accepted.", "error")
    else:
        job.status = "Accepted"
        db.session.commit()
        flash("Job accepted.", "success")
    return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))


@dashboard_bp.post("/mechanic/jobs/<int:booking_id>/start")
@role_required("mechanic", "admin")
def start_mechanic_job(booking_id):
    job = get_accessible_job(booking_id)
    if normalize_status(job.status) not in MECHANIC_ACCEPTED_STATUSES:
        flash("Accept the job before starting service.", "error")
    else:
        job.status = "In Progress"
        db.session.commit()
        flash("Service started.", "success")
    return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))


@dashboard_bp.post("/mechanic/jobs/<int:booking_id>/complete")
@role_required("mechanic", "admin")
def complete_mechanic_job(booking_id):
    job = get_accessible_job(booking_id)
    if normalize_status(job.status) not in MECHANIC_PROGRESS_STATUSES:
        flash("Start the service before completing it.", "error")
        return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))

    work_performed = request.form.get("work_performed", "").strip()
    mileage_value = request.form.get("mileage", "").strip()
    if not work_performed:
        flash("Work performed is required.", "error")
        return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))
    try:
        mileage = int(mileage_value) if mileage_value else None
    except ValueError:
        flash("Mileage must be a whole number.", "error")
        return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))
    if mileage is not None and mileage < 0:
        flash("Mileage cannot be negative.", "error")
        return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))

    charge_errors = []
    labor_charges = parse_nonnegative_decimal(
        request.form.get("labor_charges", "0"), "Labour charges", charge_errors
    )
    additional_charges = parse_nonnegative_decimal(
        request.form.get("additional_charges", "0"), "Additional charges", charge_errors
    )
    if charge_errors:
        flash(charge_errors[0], "error")
        return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))

    parts, part_error = parse_requested_parts(request.form)
    if part_error:
        flash(part_error, "error")
        return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))

    service_record = ServiceRecord(
        booking=job,
        vehicle=job.vehicle,
        mechanic_id=job.mechanic_id or current_user.id,
        service_date=date.today(),
        diagnosis=request.form.get("diagnosis", "").strip() or None,
        work_performed=work_performed,
        mileage=mileage,
        notes=request.form.get("notes", "").strip() or None,
        customer_id=job.customer_id,
        labor_charges=labor_charges,
        additional_charges=additional_charges,
    )
    job.status = "Completed"
    if mileage is not None and mileage >= job.vehicle.mileage:
        job.vehicle.mileage = mileage
    db.session.add(service_record)
    part_total = Decimal("0.00")
    for part, quantity in parts:
        part.quantity_in_stock -= int(quantity)
        selling_price = part.selling_price if part.selling_price is not None else part.unit_price
        part_total += selling_price * quantity
        db.session.add(
            PartUsage(
                part=part,
                service_record=service_record,
                quantity=quantity,
                unit_cost=part.purchase_price if part.purchase_price and part.purchase_price > 0 else part.unit_price,
            )
        )
    service_record.total_cost = labor_charges + additional_charges + part_total
    invoice = Invoice.query.filter_by(booking_id=job.id).first()
    if invoice is None:
        invoice = Invoice(
            booking_id=job.id,
            vehicle_id=job.vehicle_id,
            customer_id=job.customer_id,
            invoice_number=f"INV-{job.id:06d}",
            status="unpaid",
            subtotal=service_record.total_cost,
            tax=Decimal("0.00"),
            total=service_record.total_cost,
        )
        db.session.add(invoice)
        db.session.flush()
        if labor_charges:
            db.session.add(InvoiceItem(description="Labour charges", quantity=1, unit_price=labor_charges, total=labor_charges, invoice=invoice))
        if additional_charges:
            db.session.add(InvoiceItem(description="Additional charges", quantity=1, unit_price=additional_charges, total=additional_charges, invoice=invoice))
        for part, quantity in parts:
            selling_price = part.selling_price if part.selling_price is not None else part.unit_price
            db.session.add(InvoiceItem(part=part, invoice=invoice, description=part.name, quantity=quantity, unit_price=selling_price, total=selling_price * quantity))
    else:
        invoice.subtotal = service_record.total_cost
        invoice.total = service_record.total_cost + (invoice.tax or Decimal("0.00"))
    service_record.invoice_id = invoice.id
    db.session.add(
        Notification(
            user_id=job.customer_id,
            booking_id=job.id,
            title="Service completed",
            message=f"Your {job.service_type} service has been completed.",
            notification_type="service_completed",
        )
    )
    db.session.commit()
    flash("Service completed and customer notified.", "success")
    return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))


@dashboard_bp.route("/mechanic/jobs/<int:booking_id>/service-record/edit", methods=["GET", "POST"])
@role_required("mechanic", "admin")
def edit_mechanic_service_record(booking_id):
    job = get_accessible_job(booking_id)
    record = ServiceRecord.query.filter_by(booking_id=job.id).order_by(ServiceRecord.created_at.desc()).first_or_404()
    invoice = Invoice.query.filter_by(id=record.invoice_id).first() if record.invoice_id else Invoice.query.filter_by(booking_id=job.id).first()
    errors = []
    if request.method == "POST":
        work_performed = request.form.get("work_performed", "").strip()
        charge_errors = []
        labor_charges = parse_nonnegative_decimal(request.form.get("labor_charges", "0"), "Labour charges", charge_errors)
        additional_charges = parse_nonnegative_decimal(request.form.get("additional_charges", "0"), "Additional charges", charge_errors)
        if not work_performed:
            errors.append("Work performed is required.")
        errors.extend(charge_errors)
        if not errors:
            record.work_performed = work_performed
            record.diagnosis = request.form.get("diagnosis", "").strip() or None
            record.notes = request.form.get("notes", "").strip() or None
            record.labor_charges = labor_charges
            record.additional_charges = additional_charges
            parts_total = sum(
                (
                    (usage.part.selling_price if usage.part.selling_price is not None else usage.part.unit_price)
                    * usage.quantity
                    for usage in record.part_usages
                ),
                Decimal("0.00"),
            )
            record.total_cost = labor_charges + additional_charges + parts_total
            if invoice:
                invoice.subtotal = record.total_cost
                invoice.total = record.total_cost + (invoice.tax or Decimal("0.00"))
            db.session.commit()
            flash("Service record updated.", "success")
            return redirect(url_for("dashboard.mechanic_job_detail", booking_id=job.id))
    return render_template(
        "mechanic/service_record_form.html",
        page_title="Edit Service Record",
        job=job,
        record=record,
        invoice=invoice,
        errors=errors,
    )


@dashboard_bp.get("/mechanic/inspections")
@role_required("mechanic", "admin")
def mechanic_inspections():
    inspections = mechanic_inspections_query().order_by(Inspection.created_at.desc()).all()
    return render_template(
        "mechanic/inspections.html",
        page_title="Vehicle Inspections",
        inspections=inspections,
        is_admin=current_user.role == "admin",
    )


@dashboard_bp.get("/admin/inventory")
@role_required("admin")
def admin_inventory():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    stock_filter = request.args.get("stock", "").strip()
    query = Part.query
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(Part.name.ilike(pattern), Part.part_number.ilike(pattern), Part.supplier.ilike(pattern))
        )
    if category:
        query = query.filter(Part.category == category)
    if stock_filter == "out":
        query = query.filter(Part.quantity_in_stock == 0)
    elif stock_filter == "low":
        query = query.filter(
            Part.quantity_in_stock > 0,
            Part.quantity_in_stock <= Part.minimum_stock,
        )
    elif stock_filter == "in":
        query = query.filter(Part.quantity_in_stock > Part.minimum_stock)
    parts = query.order_by(Part.name).all()
    categories = [value for (value,) in db.session.query(Part.category).filter(Part.category.isnot(None)).distinct().order_by(Part.category).all()]
    return render_template(
        "admin/inventory.html",
        page_title="Inventory Management",
        parts=parts,
        categories=categories,
        filters={"q": search, "category": category, "stock": stock_filter},
        stock_status=part_stock_status,
    )


@dashboard_bp.route("/admin/inventory/add", methods=["GET", "POST"])
@role_required("admin")
def add_inventory_part():
    form = inventory_part_form_data()
    errors = []
    if request.method == "POST":
        form = inventory_part_form_data(request.form)
        errors, values = validate_inventory_part_form(form)
        if not errors:
            db.session.add(Part(**values))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("That part number is already in use.")
            else:
                flash("Part added to inventory.", "success")
                return redirect(url_for("dashboard.admin_inventory"))
    return render_template(
        "admin/part_form.html",
        page_title="Add Part",
        form_heading="Add inventory part",
        submit_label="Add part",
        form=form,
        errors=errors,
    )


@dashboard_bp.route("/admin/inventory/<int:part_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_inventory_part(part_id):
    part = Part.query.get_or_404(part_id)
    form = inventory_part_form_data(part)
    errors = []
    if request.method == "POST":
        form = inventory_part_form_data(request.form)
        errors, values = validate_inventory_part_form(form, part_id=part.id)
        if not errors:
            for field, value in values.items():
                setattr(part, field, value)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("That part number is already in use.")
            else:
                flash("Inventory part updated.", "success")
                return redirect(url_for("dashboard.admin_inventory"))
    return render_template(
        "admin/part_form.html",
        page_title="Edit Part",
        form_heading="Edit inventory part",
        submit_label="Save changes",
        form=form,
        errors=errors,
        part=part,
    )


@dashboard_bp.post("/admin/inventory/<int:part_id>/delete")
@role_required("admin")
def delete_inventory_part(part_id):
    part = Part.query.get_or_404(part_id)
    try:
        db.session.delete(part)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("This part cannot be deleted because it is used in service records.", "error")
    else:
        flash("Part removed from inventory.", "success")
    return redirect(url_for("dashboard.admin_inventory"))


def mechanic_jobs_query():
    query = ServiceBooking.query.join(Vehicle, ServiceBooking.vehicle_id == Vehicle.id)
    if current_user.role != "admin":
        query = query.filter(ServiceBooking.mechanic_id == current_user.id)
    return query.options(
        joinedload(ServiceBooking.vehicle),
        joinedload(ServiceBooking.customer),
        joinedload(ServiceBooking.mechanic),
    )


def mechanic_inspections_query():
    query = Inspection.query.join(ServiceBooking, Inspection.booking_id == ServiceBooking.id)
    if current_user.role != "admin":
        query = query.filter(ServiceBooking.mechanic_id == current_user.id)
    return query.options(
        joinedload(Inspection.vehicle),
        joinedload(Inspection.booking),
        joinedload(Inspection.items),
    )


def get_accessible_job(booking_id):
    return mechanic_jobs_query().filter(ServiceBooking.id == booking_id).first_or_404()


def get_admin_booking(booking_id):
    return ServiceBooking.query.options(
        joinedload(ServiceBooking.customer),
        joinedload(ServiceBooking.vehicle),
        joinedload(ServiceBooking.mechanic),
    ).filter(ServiceBooking.id == booking_id).first_or_404()


def notify_booking_customer(booking, title, message, notification_type):
    db.session.add(
        Notification(
            user_id=booking.customer_id,
            booking_id=booking.id,
            title=title,
            message=message,
            notification_type=notification_type,
        )
    )


def parse_admin_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def admin_pickup_option(notes):
    prefix = "Pickup/drop-off option: "
    if notes and notes.startswith(prefix):
        return notes.split("\n", 1)[0][len(prefix):]
    return "Not specified"


def normalize_status(status):
    return (status or "").lower().replace("_", " ")


def build_mechanic_stats(jobs):
    statuses = [normalize_status(job.status) for job in jobs]
    return {
        "today": sum(job.booking_date == date.today() for job in jobs),
        "pending": sum(status in MECHANIC_PENDING_STATUSES for status in statuses),
        "accepted": sum(status in MECHANIC_ACCEPTED_STATUSES for status in statuses),
        "in_progress": sum(status in MECHANIC_PROGRESS_STATUSES for status in statuses),
        "completed": sum(status in MECHANIC_COMPLETED_STATUSES for status in statuses),
    }


def inspection_form_values(inspection):
    values = {"notes": inspection.notes if inspection else "", "recommendations": inspection.recommendations if inspection else ""}
    item_values = {item.item_name: item for item in inspection.items} if inspection else {}
    for label, field_name in INSPECTION_CATEGORIES:
        item = item_values.get(label)
        values[field_name] = item.status if item and item.status in INSPECTION_STATUSES else "Good"
        values[f"{field_name}_notes"] = item.notes if item else ""
    return values


def inspection_form_values_from_request(form):
    values = {"notes": form.get("notes", "").strip(), "recommendations": form.get("recommendations", "").strip()}
    for label, field_name in INSPECTION_CATEGORIES:
        values[field_name] = form.get(f"status_{field_name}", "").strip()
        values[f"{field_name}_notes"] = form.get(f"notes_{field_name}", "").strip()
    return values


def validate_inspection_values(values):
    errors = []
    for label, field_name in INSPECTION_CATEGORIES:
        if values[field_name] not in INSPECTION_STATUSES:
            errors.append(f"{label} must have a valid status.")
    if len(values["notes"]) > 4000:
        errors.append("Inspection notes must be 4000 characters or fewer.")
    if len(values["recommendations"]) > 4000:
        errors.append("Recommendations must be 4000 characters or fewer.")
    return errors


def overall_inspection_status(values):
    return max(
        (values[field_name] for _, field_name in INSPECTION_CATEGORIES),
        key=lambda status: INSPECTION_STATUS_RANK[status],
    )


def parse_requested_parts(form):
    parts = []
    seen_part_ids = set()
    part_ids = form.getlist("part_id")
    quantities = form.getlist("quantity")
    for part_id_value, quantity_value in zip(part_ids, quantities):
        if not part_id_value and not quantity_value:
            continue
        try:
            part_id = int(part_id_value)
        except (TypeError, ValueError):
            return [], "Select a valid part."
        if part_id in seen_part_ids:
            return [], "A part can only be added once."
        try:
            quantity = Decimal(quantity_value)
        except (InvalidOperation, TypeError, ValueError):
            return [], "Part quantities must be valid numbers."
        if quantity <= 0 or quantity != quantity.quantize(Decimal("1")):
            return [], "Part quantities must be positive whole numbers."
        part = db.session.get(Part, part_id)
        if part is None or part.quantity_in_stock < int(quantity):
            return [], "One or more selected parts are unavailable in the current stock."
        seen_part_ids.add(part_id)
        parts.append((part, quantity))
    return parts, None


def inventory_part_form_data(source=None):
    fields = ("name", "part_number", "category", "supplier", "description", "quantity_in_stock", "minimum_stock", "purchase_price", "selling_price")
    if source is None:
        return {field: "" for field in fields}
    if hasattr(source, "get"):
        return {field: source.get(field, "").strip() for field in fields}
    return {
        field: "" if getattr(source, field, None) is None else str(getattr(source, field))
        for field in fields
    }


def validate_inventory_part_form(form, part_id=None):
    errors = []
    values = {}
    for field, label in (("name", "Part name"), ("part_number", "Part number")):
        if not form.get(field):
            errors.append(f"{label} is required.")
    quantity = parse_nonnegative_int(form.get("quantity_in_stock"), "Quantity", errors)
    minimum_stock = parse_nonnegative_int(form.get("minimum_stock"), "Minimum stock", errors)
    purchase_price = parse_nonnegative_decimal(form.get("purchase_price"), "Purchase price", errors)
    selling_price = parse_nonnegative_decimal(form.get("selling_price"), "Selling price", errors, allow_blank=True)
    duplicate = Part.query.filter(Part.part_number == form.get("part_number"))
    if part_id is not None:
        duplicate = duplicate.filter(Part.id != part_id)
    if form.get("part_number") and duplicate.first():
        errors.append("That part number is already in use.")
    if not errors:
        values = {
            "name": form["name"],
            "part_number": form["part_number"],
            "category": form.get("category") or None,
            "supplier": form.get("supplier") or None,
            "description": form.get("description") or None,
            "quantity_in_stock": quantity,
            "minimum_stock": minimum_stock,
            "purchase_price": purchase_price,
            "selling_price": selling_price,
            "unit_price": selling_price if selling_price is not None else purchase_price,
            "reorder_level": minimum_stock,
        }
    return errors, values


def parse_nonnegative_int(value, label, errors):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a whole number.")
        return 0
    if parsed < 0:
        errors.append(f"{label} cannot be negative.")
    return parsed


def parse_nonnegative_decimal(value, label, errors, allow_blank=False):
    if allow_blank and not value:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{label} must be a valid amount.")
        return Decimal("0.00")
    if parsed < 0:
        errors.append(f"{label} cannot be negative.")
    return parsed


def part_stock_status(part):
    if part.quantity_in_stock == 0:
        return {"label": "Out of Stock", "tone": "danger"}
    if part.quantity_in_stock <= part.minimum_stock:
        return {"label": "Low Stock", "tone": "warning"}
    return {"label": "In Stock", "tone": "success"}


def report_months():
    current_month = date.today().replace(day=1)
    months = []
    for offset in range(11, -1, -1):
        month_index = current_month.month - 1 - offset
        year = current_month.year + month_index // 12
        month = month_index % 12 + 1
        months.append({"key": (year, month), "label": f"{month_abbr[month]} {str(year)[2:]}"})
    return months


def monthly_booking_data():
    rows = db.session.query(
        extract("year", ServiceBooking.created_at).label("year"),
        extract("month", ServiceBooking.created_at).label("month"),
        func.count(ServiceBooking.id).label("total"),
    ).group_by("year", "month").all()
    values = {(int(row.year), int(row.month)): row.total for row in rows}
    return [{"label": month["label"], "value": values.get(month["key"], 0)} for month in report_months()]


def monthly_revenue_data():
    paid_statuses = {"paid", "received", "payment received"}
    rows = db.session.query(
        extract("year", Invoice.created_at).label("year"),
        extract("month", Invoice.created_at).label("month"),
        func.coalesce(func.sum(Invoice.total), 0).label("total"),
    ).filter(func.lower(Invoice.status).in_(paid_statuses)).group_by("year", "month").all()
    values = {(int(row.year), int(row.month)): float(row.total or 0) for row in rows}
    return [{"label": month["label"], "value": values.get(month["key"], 0)} for month in report_months()]


def service_type_data():
    rows = db.session.query(
        ServiceBooking.service_type, func.count(ServiceBooking.id).label("total")
    ).group_by(ServiceBooking.service_type).order_by(func.count(ServiceBooking.id).desc()).all()
    return [{"label": label, "value": total} for label, total in rows]


def booking_status_data():
    rows = db.session.query(
        func.lower(ServiceBooking.status).label("status"), func.count(ServiceBooking.id).label("total")
    ).group_by(func.lower(ServiceBooking.status)).order_by(func.count(ServiceBooking.id).desc()).all()
    return [{"label": status.replace("_", " ").title(), "value": total} for status, total in rows]


@dashboard_bp.get("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    pending_statuses = {"requested", "pending", "confirmed", "assigned"}
    active_statuses = {"accepted", "in progress", "work in progress", "inspection", "vehicle received", "quality check"}
    completed_statuses = {"completed", "closed"}
    paid_statuses = {"paid", "received", "payment received"}
    pending_payment_statuses = {"unpaid", "pending", "overdue", "partially paid"}
    total_revenue = db.session.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
        func.lower(Invoice.status).in_(paid_statuses)
    ).scalar()
    pending_payments = db.session.query(func.coalesce(func.sum(Invoice.total), 0)).filter(
        func.lower(Invoice.status).in_(pending_payment_statuses)
    ).scalar()
    bookings = ServiceBooking.query.order_by(ServiceBooking.created_at.desc()).all()
    recent_bookings = ServiceBooking.query.options(
        joinedload(ServiceBooking.customer), joinedload(ServiceBooking.vehicle)
    ).order_by(ServiceBooking.created_at.desc()).limit(6).all()
    recent_customers = User.query.filter_by(role="customer").order_by(User.created_at.desc()).limit(6).all()
    recent_services = ServiceRecord.query.join(
        ServiceBooking, ServiceRecord.booking_id == ServiceBooking.id
    ).filter(func.lower(ServiceBooking.status).in_(completed_statuses)).options(
        joinedload(ServiceRecord.vehicle), joinedload(ServiceRecord.booking)
    ).order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc()).limit(6).all()
    recent_payments = Invoice.query.filter(
        func.lower(Invoice.status).in_(paid_statuses)
    ).options(joinedload(Invoice.customer), joinedload(Invoice.vehicle)).order_by(
        Invoice.paid_at.desc(), Invoice.created_at.desc()
    ).limit(6).all()
    monthly_bookings = monthly_booking_data()
    monthly_revenue = monthly_revenue_data()
    service_type_counts = service_type_data()
    booking_status_counts = booking_status_data()
    return render_template(
        "admin/dashboard.html",
        page_title="Admin Dashboard",
        stats={
            "customers": User.query.filter_by(role="customer").count(),
            "vehicles": Vehicle.query.count(),
            "bookings": len(bookings),
            "pending_bookings": sum(normalize_status(booking.status) in pending_statuses for booking in bookings),
            "active_services": sum(normalize_status(booking.status) in active_statuses for booking in bookings),
            "completed_services": sum(normalize_status(booking.status) in completed_statuses for booking in bookings),
            "revenue": total_revenue,
            "pending_payments": pending_payments,
            "mechanics": User.query.filter_by(role="mechanic").count(),
        },
        monthly_bookings=monthly_bookings,
        monthly_revenue=monthly_revenue,
        service_type_counts=service_type_counts,
        booking_status_counts=booking_status_counts,
        chart_max={
            "bookings": max((item["value"] for item in monthly_bookings), default=0),
            "revenue": max((item["value"] for item in monthly_revenue), default=0),
            "service_types": max((item["value"] for item in service_type_counts), default=0),
            "statuses": max((item["value"] for item in booking_status_counts), default=0),
        },
        recent_bookings=recent_bookings,
        recent_customers=recent_customers,
        recent_services=recent_services,
        recent_payments=recent_payments,
    )


@dashboard_bp.get("/admin/bookings")
@role_required("admin")
def admin_bookings():
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    service_type = request.args.get("service_type", "").strip()
    date_value = request.args.get("date", "").strip()
    query = ServiceBooking.query.join(User, ServiceBooking.customer_id == User.id).join(
        Vehicle, ServiceBooking.vehicle_id == Vehicle.id
    ).options(
        joinedload(ServiceBooking.customer), joinedload(ServiceBooking.vehicle), joinedload(ServiceBooking.mechanic)
    )


@dashboard_bp.get("/admin/service-records")
@role_required("admin")
def admin_service_records():
    records = ServiceRecord.query.options(
        joinedload(ServiceRecord.customer),
        joinedload(ServiceRecord.vehicle),
        joinedload(ServiceRecord.booking),
        joinedload(ServiceRecord.mechanic),
        joinedload(ServiceRecord.invoice),
        joinedload(ServiceRecord.part_usages).joinedload(PartUsage.part),
    ).order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc()).all()
    return render_template(
        "admin/service_records.html",
        page_title="Service Records",
        records=records,
    )
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            ServiceBooking.service_type.ilike(pattern),
            User.name.ilike(pattern),
            User.email.ilike(pattern),
            Vehicle.registration_number.ilike(pattern),
        ))
    if status:
        query = query.filter(func.lower(ServiceBooking.status) == status.lower())
    if service_type:
        query = query.filter(ServiceBooking.service_type == service_type)
    parsed_date = parse_admin_date(date_value)
    if parsed_date:
        query = query.filter(ServiceBooking.booking_date == parsed_date)
    bookings = query.order_by(ServiceBooking.booking_date.desc(), ServiceBooking.booking_time.desc()).all()
    service_types = [value for (value,) in db.session.query(ServiceBooking.service_type).distinct().order_by(ServiceBooking.service_type).all()]
    return render_template(
        "admin/bookings.html",
        page_title="Booking Management",
        bookings=bookings,
        statuses=ADMIN_BOOKING_STATUSES,
        service_types=service_types,
        filters={"q": search, "status": status, "service_type": service_type, "date": date_value},
    )


@dashboard_bp.get("/admin/bookings/<int:booking_id>")
@role_required("admin")
def admin_booking_detail(booking_id):
    booking = get_admin_booking(booking_id)
    mechanics = User.query.filter_by(role="mechanic").order_by(User.name).all()
    active_job_statuses = {"requested", "pending", "confirmed", "assigned", "accepted", "in progress", "work in progress", "inspection", "vehicle received", "quality check"}
    workload_rows = db.session.query(
        ServiceBooking.mechanic_id, func.count(ServiceBooking.id)
    ).filter(
        ServiceBooking.mechanic_id.isnot(None),
        func.lower(ServiceBooking.status).in_(active_job_statuses),
    ).group_by(ServiceBooking.mechanic_id).all()
    mechanic_workloads = {mechanic_id: count for mechanic_id, count in workload_rows}
    mechanic_current_jobs = {}
    mechanic_ids = [mechanic.id for mechanic in mechanics]
    if mechanic_ids:
        current_jobs = ServiceBooking.query.filter(
            ServiceBooking.mechanic_id.in_(mechanic_ids),
            func.lower(ServiceBooking.status).in_(active_job_statuses),
        ).options(joinedload(ServiceBooking.vehicle)).order_by(
            ServiceBooking.booking_date, ServiceBooking.booking_time
        ).all()
        for current_job in current_jobs:
            mechanic_current_jobs.setdefault(current_job.mechanic_id, []).append(current_job)
    return render_template(
        "admin/booking_detail.html",
        page_title="Booking Review",
        booking=booking,
        mechanics=mechanics,
        statuses=ADMIN_BOOKING_STATUSES,
        pickup_option=admin_pickup_option(booking.notes),
        mechanic_workloads=mechanic_workloads,
        mechanic_current_jobs=mechanic_current_jobs,
    )


@dashboard_bp.post("/admin/bookings/<int:booking_id>/approve")
@role_required("admin")
def approve_booking(booking_id):
    booking = get_admin_booking(booking_id)
    if normalize_status(booking.status) not in {"requested", "pending", "confirmed"}:
        flash("Only requested bookings can be approved.", "error")
    else:
        booking.status = "Approved"
        notify_booking_customer(booking, "Booking approved", "Your service booking has been approved by the service team.", "booking_approved")
        db.session.commit()
        flash("Booking approved.", "success")
    return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))


@dashboard_bp.post("/admin/bookings/<int:booking_id>/reject")
@role_required("admin")
def reject_booking(booking_id):
    booking = get_admin_booking(booking_id)
    if normalize_status(booking.status) in {"completed", "closed", "rejected", "cancelled"}:
        flash("This booking cannot be rejected.", "error")
    else:
        booking.status = "Rejected"
        notify_booking_customer(booking, "Booking rejected", "Your service booking request was rejected by the service team.", "booking_rejected")
        db.session.commit()
        flash("Booking rejected.", "success")
    return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))


@dashboard_bp.post("/admin/bookings/<int:booking_id>/reschedule")
@role_required("admin")
def reschedule_booking(booking_id):
    booking = get_admin_booking(booking_id)
    new_date = parse_admin_date(request.form.get("booking_date", ""))
    try:
        new_time = datetime.strptime(request.form.get("booking_time", ""), "%H:%M").time()
    except (TypeError, ValueError):
        new_time = None
    if not new_date or not new_time or new_date < date.today():
        flash("Choose a valid future date and time.", "error")
        return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))
    conflict = ServiceBooking.query.filter(
        ServiceBooking.vehicle_id == booking.vehicle_id,
        ServiceBooking.booking_date == new_date,
        ServiceBooking.booking_time == new_time,
        ServiceBooking.id != booking.id,
        ~func.lower(ServiceBooking.status).in_({"cancelled", "rejected", "completed", "closed"}),
    ).first()
    if conflict:
        flash("That vehicle already has a booking at the selected time.", "error")
    else:
        booking.booking_date = new_date
        booking.booking_time = new_time
        notify_booking_customer(booking, "Booking rescheduled", f"Your {booking.service_type} booking was moved to {new_date.strftime('%d %b %Y')} at {new_time.strftime('%H:%M')}.", "booking_rescheduled")
        db.session.commit()
        flash("Booking rescheduled.", "success")
    return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))


@dashboard_bp.post("/admin/bookings/<int:booking_id>/assign")
@role_required("admin")
def assign_booking_mechanic(booking_id):
    booking = get_admin_booking(booking_id)
    mechanic = User.query.filter_by(id=request.form.get("mechanic_id"), role="mechanic").first()
    if normalize_status(booking.status) in {"completed", "closed", "rejected", "cancelled"}:
        flash("A terminal booking cannot be assigned.", "error")
    elif mechanic is None:
        flash("Select a valid mechanic.", "error")
    else:
        previous_mechanic = booking.mechanic
        booking.mechanic_id = mechanic.id
        booking.status = "Assigned"
        if previous_mechanic and previous_mechanic.id != mechanic.id:
            db.session.add(Notification(user_id=previous_mechanic.id, booking_id=booking.id, title="Job reassigned", message=f"The {booking.service_type} job has been reassigned to another mechanic.", notification_type="job_reassigned"))
        notify_booking_customer(booking, "Mechanic assigned", f"{mechanic.name} has been assigned to your service booking.", "mechanic_assigned")
        db.session.add(Notification(user_id=mechanic.id, booking_id=booking.id, title="New job assigned", message=f"A {booking.service_type} job has been assigned to you.", notification_type="job_assigned"))
        db.session.commit()
        flash("Mechanic assigned.", "success")
    return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))


@dashboard_bp.post("/admin/bookings/<int:booking_id>/remove-assignment")
@role_required("admin")
def remove_booking_mechanic(booking_id):
    booking = get_admin_booking(booking_id)
    previous_mechanic = booking.mechanic
    if previous_mechanic is None:
        flash("This booking has no assigned mechanic.", "error")
    elif normalize_status(booking.status) in {"completed", "closed"}:
        flash("A completed booking cannot have its mechanic removed.", "error")
    else:
        booking.mechanic_id = None
        booking.status = "Approved"
        db.session.add(Notification(user_id=previous_mechanic.id, booking_id=booking.id, title="Job assignment removed", message=f"Your assignment for the {booking.service_type} job was removed.", notification_type="job_unassigned"))
        notify_booking_customer(booking, "Mechanic assignment updated", "Your booking is being reassigned by the service team.", "mechanic_unassigned")
        db.session.commit()
        flash("Mechanic assignment removed.", "success")
    return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))


@dashboard_bp.post("/admin/bookings/<int:booking_id>/status")
@role_required("admin")
def change_booking_status(booking_id):
    booking = get_admin_booking(booking_id)
    new_status = request.form.get("status", "").strip()
    if new_status not in ADMIN_BOOKING_STATUSES:
        flash("Select a valid booking status.", "error")
    else:
        booking.status = new_status
        notify_booking_customer(booking, f"Booking status updated: {new_status}", f"Your {booking.service_type} booking is now {new_status.lower()}.", "booking_status")
        db.session.commit()
        flash("Booking status updated.", "success")
    return redirect(url_for("dashboard.admin_booking_detail", booking_id=booking.id))


@dashboard_bp.get("/admin/customers")
@role_required("admin")
def admin_customers():
    return render_template(
        "dashboard.html", page_title="Customer Management", role_label="Admin Customers"
    )


@dashboard_bp.get("/admin/vehicles")
@role_required("admin")
def admin_vehicles():
    return render_template(
        "dashboard.html", page_title="Vehicle Management", role_label="Admin Vehicles"
    )



