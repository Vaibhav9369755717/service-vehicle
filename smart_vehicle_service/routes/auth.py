import re
from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from models import User, db


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def is_safe_url(target):
    if not target:
        return False
    host_url = urlparse(request.host_url)
    target_url = urlparse(urljoin(request.host_url, target))
    return target_url.scheme in {"http", "https"} and target_url.netloc == host_url.netloc


def role_dashboard(role):
    return {
        "customer": "customer.customer_dashboard",
        "mechanic": "dashboard.mechanic_dashboard",
        "admin": "dashboard.admin_dashboard",
    }.get(role, "home")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for(role_dashboard(current_user.role)))

    form = {"name": "", "email": "", "phone": ""}
    if request.method == "POST":
        form = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "phone": request.form.get("phone", "").strip(),
        }
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all(form.values()) or not password or not confirm_password:
            flash("Please complete all required fields.", "error")
        elif not EMAIL_PATTERN.fullmatch(form["email"]):
            flash("Please enter a valid email address.", "error")
        elif len(password) < MIN_PASSWORD_LENGTH:
            flash("Password must be at least 8 characters long.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif User.query.filter_by(email=form["email"]).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(
                name=form["name"],
                email=form["email"],
                phone=form["phone"],
                password_hash=generate_password_hash(password),
                role="customer",
            )
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("An account with that email already exists.", "error")
            else:
                flash("Registration successful. You can now log in.", "success")
                return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(role_dashboard(current_user.role)))

    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user is None or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
        else:
            login_user(user)
            next_url = request.args.get("next")
            if is_safe_url(next_url) and next_url.startswith(f"/{user.role}/"):
                return redirect(next_url)
            return redirect(url_for(role_dashboard(user.role)))

    return render_template("auth/login.html", email=email)


@auth_bp.post("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))