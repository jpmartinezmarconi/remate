from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
import smtplib
import ssl
from urllib.parse import urljoin, urlsplit

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import or_

from app.database import db
from models.user import User
from .security import csrf_protect


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
PASSWORD_RESET_MAX_AGE = 3600
PASSWORD_RESET_COOLDOWN = timedelta(minutes=1)


def _password_reset_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="password-reset-v1"
    )


def _send_password_reset_email(user: User, token: str) -> None:
    host = current_app.config.get("SMTP_HOST")
    port = current_app.config.get("SMTP_PORT", 587)
    username = current_app.config.get("SMTP_USERNAME")
    password = current_app.config.get("SMTP_PASSWORD")
    sender = current_app.config.get("SMTP_FROM_EMAIL")
    base_url = current_app.config.get("PUBLIC_BASE_URL")
    if not host or not sender or not username or not password or not base_url:
        raise RuntimeError(
            "SMTP and PUBLIC_BASE_URL settings are required for password recovery."
        )
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise RuntimeError("SMTP_PORT must be an integer between 1 and 65535.")
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise RuntimeError("PUBLIC_BASE_URL must be an absolute HTTP or HTTPS URL.")

    reset_path = url_for("auth.reset_password", token=token)
    reset_url = urljoin(base_url.rstrip("/") + "/", reset_path.lstrip("/"))
    message = EmailMessage()
    message["Subject"] = "Restablecé tu contraseña · Remate Martínez"
    message["From"] = sender
    message["To"] = user.email
    message.set_content(
        f"Hola {user.full_name or user.username}:\n\n"
        "Recibimos una solicitud para restablecer la contraseña de tu cuenta. "
        "Usá este enlace dentro de la próxima hora:\n\n"
        f"{reset_url}\n\n"
        "Si no solicitaste este cambio, podés ignorar este mensaje.\n\n"
        "Remate Martínez"
    )
    with smtplib.SMTP(host, port, timeout=30) as mail_server:
        mail_server.starttls(context=ssl.create_default_context())
        mail_server.login(username, password)
        mail_server.send_message(message)


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


@auth_bp.route("/recuperar-contrasena", methods=["GET", "POST"])
@csrf_protect
def request_password_reset():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first() if email else None
        if user is not None:
            now = datetime.now(timezone.utc)
            last_requested = user.password_reset_requested_at
            if last_requested is not None and last_requested.tzinfo is None:
                last_requested = last_requested.replace(tzinfo=timezone.utc)
            if (
                last_requested is None
                or now - last_requested >= PASSWORD_RESET_COOLDOWN
            ):
                token = _password_reset_serializer().dumps(
                    {"user_id": user.id, "password_hash": user.password_hash}
                )
                try:
                    _send_password_reset_email(user, token)
                except (OSError, smtplib.SMTPException, RuntimeError):
                    current_app.logger.exception(
                        "Could not send password reset email for user %s.", user.id
                    )
                else:
                    user.password_reset_requested_at = now
                    db.session.commit()
        flash(
            "Si el correo está registrado, recibirás un enlace para cambiar la contraseña.",
            "info",
        )
        return redirect(url_for("auth.request_password_reset"))
    return render_template("password_reset_request.html")


@auth_bp.route("/restablecer-contrasena/<token>", methods=["GET", "POST"])
@csrf_protect
def reset_password(token: str):
    try:
        payload = _password_reset_serializer().loads(
            token, max_age=PASSWORD_RESET_MAX_AGE
        )
    except (BadSignature, SignatureExpired):
        payload = None

    user = None
    if isinstance(payload, dict) and isinstance(payload.get("user_id"), int):
        user = db.session.get(User, payload["user_id"])
    if (
        user is None
        or not isinstance(payload, dict)
        or payload.get("password_hash") != user.password_hash
    ):
        flash("El enlace no es válido o ya venció. Solicitá uno nuevo.", "warning")
        return redirect(url_for("auth.request_password_reset"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirmation = request.form.get("password_confirmation", "")
        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "danger")
        elif password != password_confirmation:
            flash("Las contraseñas no coinciden.", "danger")
        else:
            user.set_password(password)
            user.password_reset_requested_at = None
            db.session.commit()
            flash("Tu contraseña se actualizó. Ya podés ingresar.", "success")
            return redirect(url_for("auth.login"))
    return render_template("password_reset_form.html")


@auth_bp.post("/salir")
@csrf_protect
def logout():
    session.clear()
    flash("Tu sesión se cerró correctamente.", "info")
    return redirect(url_for("auction.home"))
