from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from app.database import db
from models.user import User
from .security import csrf_protect


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url() -> str | None:
    target = request.args.get("next", "")
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("current_user") is None:
            flash("Iniciá sesión para continuar.", "warning")
            next_url = (
                request.path
                if request.method in {"GET", "HEAD"}
                else request.referrer or url_for("auction.home")
            )
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/registro", methods=["GET", "POST"])
@csrf_protect
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        shipping_address = request.form.get("shipping_address", "").strip()
        city = request.form.get("city", "").strip()
        postal_code = request.form.get("postal_code", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 80:
            flash("El nombre de usuario debe tener entre 3 y 80 caracteres.", "danger")
        elif not full_name or len(full_name) > 160:
            flash("Ingresá tu nombre completo.", "danger")
        elif "@" not in email or len(email) > 255:
            flash("Ingresá un correo electrónico válido.", "danger")
        elif not phone or len(phone) > 40:
            flash("Ingresá un teléfono válido.", "danger")
        elif not shipping_address or len(shipping_address) > 255:
            flash("Ingresá una dirección de envío válida.", "danger")
        elif not city or len(city) > 100:
            flash("Ingresá tu ciudad.", "danger")
        elif not postal_code or len(postal_code) > 20:
            flash("Ingresá tu código postal.", "danger")
        elif len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "danger")
        elif User.query.filter(or_(User.username == username, User.email == email)).first():
            flash("Ese usuario o correo ya está registrado.", "warning")
        else:
            user = User(
                username=username,
                full_name=full_name,
                email=email,
                phone=phone,
                shipping_address=shipping_address,
                city=city,
                postal_code=postal_code,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            flash("¡Tu cuenta está pronta! Bienvenido/a a Remate Martínez.", "success")
            return redirect(url_for("account.dashboard"))
    return render_template("register.html")


@auth_bp.route("/ingresar", methods=["GET", "POST"])
@csrf_protect
def login():
    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            or_(User.email == identity.lower(), User.username == identity)
        ).first()
        if user is None or not user.check_password(password):
            flash("Usuario, correo o contraseña incorrectos.", "danger")
        else:
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            flash(f"¡Qué bueno verte, {user.username}!", "success")
            return redirect(_safe_next_url() or url_for("auction.home"))
    return render_template("login.html")


@auth_bp.post("/salir")
@csrf_protect
def logout():
    session.clear()
    flash("Tu sesión se cerró correctamente.", "info")
    return redirect(url_for("auction.home"))
