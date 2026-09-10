from flask import Blueprint, render_template

from routes.decorators import role_required


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/mechanic/dashboard")
@role_required("mechanic")
def mechanic_dashboard():
    return render_template(
        "dashboard.html", page_title="Mechanic Dashboard", role_label="Mechanic"
    )


@dashboard_bp.get("/mechanic/jobs")
@role_required("mechanic")
def mechanic_jobs():
    return render_template(
        "dashboard.html", page_title="Assigned Jobs", role_label="Mechanic Jobs"
    )


@dashboard_bp.get("/mechanic/inspections")
@role_required("mechanic")
def mechanic_inspections():
    return render_template(
        "dashboard.html", page_title="Inspections", role_label="Mechanic Inspections"
    )


@dashboard_bp.get("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    return render_template(
        "dashboard.html", page_title="Admin Dashboard", role_label="Administrator"
    )


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


@dashboard_bp.get("/admin/inventory")
@role_required("admin")
def admin_inventory():
    return render_template(
        "dashboard.html", page_title="Inventory Management", role_label="Admin Inventory"
    )

