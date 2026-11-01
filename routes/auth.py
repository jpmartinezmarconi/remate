from functools import wraps

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from app.database import db
from models.user import User
from .security import csrf_protect


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("current_user") is None:
            flash("Iniciá sesión para continuar.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@auth_bp.route("/registro", methods=["GET", "POST"])
@csrf_protect
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 80:
            flash("El nombre de usuario debe tener entre 3 y 80 caracteres.", "danger")
        elif "@" not in email or len(email) > 255:
            flash("Ingresá un correo electrónico válido.", "danger")
        elif len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "danger")
        elif User.query.filter(or_(User.username == username, User.email == email)).first():
            flash("Ese usuario o correo ya está registrado.", "warning")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            session.clear()
            session["user_id"] = user.id
            session.permanent = True
            flash("¡Tu cuenta está pronta! Bienvenido/a a Remate Martínez.", "success")
            return redirect(url_for("auction.home"))
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
            return redirect(url_for("auction.home"))
    return render_template("login.html")


@auth_bp.post("/salir")
@csrf_protect
def logout():
    session.clear()
    flash("Tu sesión se cerró correctamente.", "info")
    return redirect(url_for("auction.home"))
