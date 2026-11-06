from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html import escape
import hmac
import re
from io import BytesIO
from functools import wraps
import smtplib
import ssl
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from app.auction_reminders import _mail_configuration, send_due_auction_outbid_notifications
from app.database import db
from app.mail_message import transactional_message
from models.auction import Auction
from models.auction_group import AuctionGroup
from models.auction_image import AuctionImage
from models.auction_payment import AuctionPayment
from models.bid import Bid
from models.user import User
from .security import csrf_protect


private_area_bp = Blueprint("private_area", __name__, url_prefix="/area-privada")
MAX_IMAGE_SIZE = 8 * 1024 * 1024
MAX_PRICE = Decimal("9999999999.99")
ALLOWED_IMAGE_TYPES = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def private_area_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("PRIVATE_AREA_PASSWORD"):
            current_app.logger.error("PASSWORD_AREA_PRIVADA is not configured.")
            abort(503, description="El área privada no está configurada.")
        if not session.get("private_area_authenticated"):
            return redirect(url_for("private_area.login"))
        return view(*args, **kwargs)

    return wrapped


def _image_content_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ALLOWED_IMAGE_TYPES["jpeg"]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ALLOWED_IMAGE_TYPES["png"]
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ALLOWED_IMAGE_TYPES["gif"]
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ALLOWED_IMAGE_TYPES["webp"]
    return None


def _uploaded_photos() -> list[AuctionImage] | None:
    photos = []
    for uploaded in request.files.getlist("photos"):
        if not uploaded.filename:
            continue
        data = uploaded.stream.read(MAX_IMAGE_SIZE + 1)
        if len(data) > MAX_IMAGE_SIZE:
            flash("Cada foto puede pesar como máximo 8 MB.", "danger")
            return None
        content_type = _image_content_type(data)
        if content_type is None:
            flash("Usá fotos JPG, PNG, GIF o WebP.", "danger")
            return None
        filename = secure_filename(uploaded.filename) or "foto"
        photos.append(
            AuctionImage(
                filename=filename[:255],
                content_type=content_type,
                data=data,
            )
        )
    return photos


def _featured_group_count(now: datetime) -> int:
    return (
        db.session.query(Auction.group_name)
        .filter(
            Auction.featured_on_home.is_(True),
            Auction.closes_at > now,
        )
        .distinct()
        .count()
    )


def _group_has_active_feature(group_name: str, now: datetime) -> bool:
    return (
        Auction.query.filter(
            Auction.group_name == group_name,
            Auction.featured_on_home.is_(True),
            Auction.closes_at > now,
        ).first()
        is not None
    )


def _feature_limit_message(group_name: str, now: datetime) -> str | None:
    featured_count = Auction.query.filter(
        Auction.group_name == group_name,
        Auction.featured_on_home.is_(True),
        Auction.closes_at > now,
    ).count()
    if featured_count >= 5:
        return "Cada grupo puede tener como máximo cinco lotes destacados."
    if not _group_has_active_feature(group_name, now) and _featured_group_count(now) >= 5:
        return "La portada admite como máximo cinco grupos de lotes."
    return None


@private_area_bp.route("", methods=["GET", "POST"])
@csrf_protect
def login():
    configured_password = current_app.config.get("PRIVATE_AREA_PASSWORD")
    if not configured_password:
        current_app.logger.error("PASSWORD_AREA_PRIVADA is not configured.")
        abort(503, description="El área privada no está configurada.")

    if session.get("private_area_authenticated"):
        return redirect(url_for("private_area.dashboard"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if hmac.compare_digest(
            password.encode("utf-8"), configured_password.encode("utf-8")
        ):
            session["private_area_authenticated"] = True
            session.permanent = True
            return redirect(url_for("private_area.dashboard"))
        flash("La contraseña ingresada no es correcta.", "danger")
    return render_template("private_login.html")


@private_area_bp.post("/salir")
@private_area_required
@csrf_protect
def logout():
    session.pop("private_area_authenticated", None)
    flash("Se cerró la sesión del área privada.", "info")
    return redirect(url_for("private_area.login"))


@private_area_bp.get("/panel")
@private_area_required
def dashboard():
    auctions = Auction.query.order_by(Auction.created_at.desc(), Auction.id.desc()).all()
    groups = AuctionGroup.query.order_by(AuctionGroup.name.asc()).all()
    photo_counts = dict(
        db.session.query(AuctionImage.auction_id, func.count(AuctionImage.id))
        .group_by(AuctionImage.auction_id)
        .all()
    )
    return render_template(
        "private_dashboard.html",
        auctions=auctions,
        photo_counts=photo_counts,
        groups=groups,
        min_start_time=(
            (datetime.now(timezone.utc) + timedelta(minutes=1))
            .astimezone(ZoneInfo("America/Montevideo"))
            .strftime("%Y-%m-%dT%H:%M")
        ),
    )


@private_area_bp.get("/historial-pujas")
@private_area_required
def bid_history():
    bids = (
        Bid.query.options(joinedload(Bid.auction), joinedload(Bid.bidder))
        .order_by(Bid.created_at.desc(), Bid.id.desc())
        .all()
    )
    return render_template("private_bid_history.html", bids=bids)


@private_area_bp.get("/ventas")
@private_area_required
def sales():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    closed_bids = (
        Bid.query.join(Auction)
        .options(joinedload(Bid.auction), joinedload(Bid.bidder))
        .filter(Auction.closes_at <= now)
        .order_by(
            Bid.auction_id.asc(),
            Bid.amount.desc(),
            Bid.created_at.asc(),
            Bid.id.asc(),
        )
        .all()
    )
    winning_bids = {}
    for bid in closed_bids:
        winning_bids.setdefault(bid.auction_id, bid)
    sales = sorted(
        winning_bids.values(),
        key=lambda bid: (bid.auction.closes_at, bid.auction.id),
        reverse=True,
    )
    return render_template("private_sales.html", sales=sales)


@private_area_bp.post("/ventas/reintentar-avisos")
@private_area_required
@csrf_protect
def retry_outbid_notifications():
    try:
        sent = send_due_auction_outbid_notifications()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not retry all pending outbid notifications.")
        flash("No se pudieron enviar todos los avisos pendientes. Revisá los registros.", "danger")
    else:
        flash(f"Avisos de puja superada enviados: {sent}.", "success")
    return redirect(url_for("private_area.sales"))


@private_area_bp.post("/ventas/enviar-correo-prueba")
@private_area_required
@csrf_protect
def send_winner_test_email():
    recipient = request.form.get("recipient", "inforemateonline@gmail.com").strip()
    if len(recipient) > 254 or not re.fullmatch(r"[^\s@<>(),;:]+@[^\s@<>(),;:]+\.[^\s@<>(),;:]+", recipient):
        flash("Ingresá una dirección de correo válida para la prueba.", "danger")
        return redirect(url_for("private_area.sales"))
    try:
        host, port, username, password, sender, base_url = _mail_configuration()
    except RuntimeError:
        current_app.logger.exception(
            "Could not configure the winner test email from environment settings."
        )
        flash(
            "No se pudo preparar el correo de prueba. Revisá la configuración SMTP "
            "y PUBLIC_BASE_URL en Render.",
            "danger",
        )
        return redirect(url_for("private_area.sales"))
    auction_url = urljoin(base_url.rstrip("/") + "/", "subastas-activas")
    amount = "$U 1,500.00"
    total = "$U 1,800.00"
    subject = "¡Ganaste la subasta! · Lote de prueba DEMO-001"
    text_body = (
        "Hola:\n\n"
        "¡Felicitaciones! Ganaste la subasta del lote de prueba DEMO-001.\n\n"
        "Artículo: Ejemplo de lote ganado\n"
        "Oferta ganadora: $U 1,500.00\n"
        "Comisión (20%): $U 300.00\n"
        "Total de ejemplo: $U 1,800.00\n"
        "Método de pago: todavía no registrado\n\n"
        f"Podés ver los remates en curso acá: {auction_url}\n\n"
        "Este es un correo de prueba. No se creó una subasta, puja ni pago real.\n\n"
        "Remate Martínez"
    )
    message = transactional_message(sender, recipient, subject)
    message.set_content(text_body)
    message.add_alternative(
        "<!doctype html><html lang=\"es\"><body style=\"margin:0;padding:24px;"
        "background:#f2f5f8;font-family:Arial,sans-serif;color:#1f2937\">"
        "<main style=\"max-width:600px;margin:auto;padding:28px;background:#fff;"
        "border-radius:12px\"><p style=\"margin:0 0 8px;color:#64748b\">"
        "REMATE MARTÍNEZ</p><h1 style=\"margin:0 0 16px;font-size:24px\">"
        "¡Ganaste la subasta!</h1><p style=\"display:inline-block;padding:7px 12px;"
        "border-radius:20px;background:#e8f1fb;color:#064584\"><strong>"
        "Lote de prueba DEMO-001</strong></p><h2 style=\"font-size:20px\">"
        "Ejemplo de lote ganado</h2><p>¡Felicitaciones! Tu oferta fue la ganadora.</p>"
        "<table style=\"width:100%;border-collapse:collapse\">"
        "<tr><td style=\"padding:8px 0\">Oferta ganadora</td>"
        f"<td style=\"padding:8px 0;text-align:right\"><strong>{amount}</strong></td></tr>"
        "<tr><td style=\"padding:8px 0\">Comisión (20%)</td>"
        "<td style=\"padding:8px 0;text-align:right\">$U 300.00</td></tr>"
        "<tr><td style=\"padding:8px 0;border-top:1px solid #e5e7eb\">"
        "<strong>Total de ejemplo</strong></td>"
        f"<td style=\"padding:8px 0;text-align:right;border-top:1px solid #e5e7eb\">"
        f"<strong>{total}</strong></td></tr></table>"
        "<p>Método de pago: todavía no registrado.</p>"
        f"<p style=\"margin:24px 0\"><a href=\"{escape(auction_url, quote=True)}\" "
        "style=\"display:inline-block;padding:12px 18px;background:#064584;"
        "color:white;text-decoration:none;border-radius:6px\">Ver remates en curso</a></p>"
        "<p style=\"padding:12px;background:#fff8e6;border-radius:6px\">"
        "<strong>Correo de prueba:</strong> no se creó una subasta, puja ni pago real."
        "</p><hr style=\"border:0;border-top:1px solid #e5e7eb\">"
        "<p style=\"margin-bottom:0;color:#64748b\">Remate Martínez</p>"
        "</main></body></html>",
        subtype="html",
    )

    try:
        direct_tls = request.form.get("direct_tls") == "1" and host == "smtp.gmail.com"
        if direct_tls:
            connection = smtplib.SMTP_SSL(
                host, 465, timeout=30, context=ssl.create_default_context()
            )
        else:
            connection = smtplib.SMTP(host, port, timeout=30)
        with connection as mail_server:
            if not direct_tls:
                mail_server.starttls(context=ssl.create_default_context())
            mail_server.login(username, password)
            mail_server.send_message(message)
    except (OSError, smtplib.SMTPException):
        current_app.logger.exception("Could not send the winner test email.")
        flash(
            "No se pudo enviar el correo de prueba. Revisá la configuración SMTP.",
            "danger",
        )
    else:
        flash(f"Correo de prueba enviado a {recipient}.", "success")
    return redirect(url_for("private_area.sales"))


@private_area_bp.get("/clientes")
@private_area_required
def registered_customers():
    users = User.query.order_by(User.created_at.desc(), User.id.desc()).all()
    return render_template("private_customers.html", users=users)


@private_area_bp.post("/lotes")
@private_area_required
@csrf_protect
def create_auction():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    lot_number = request.form.get("lot_number", "").strip()
    group_id = request.form.get("group_id", "").strip()
    sale_mode = request.form.get("sale_mode", "")
    start_mode = request.form.get("start_mode", "")
    try:
        starting_price = Decimal(request.form.get("starting_price", "").replace(",", "."))
        commission_percent = Decimal(
            request.form.get("commission_percent", "0").replace(",", ".")
        )
        quantity = int(request.form.get("quantity", "1"))
        duration_hours = int(request.form.get("duration_hours", ""))
    except (InvalidOperation, ValueError):
        flash("Revisá los valores de precio, comisión, cantidad y duración.", "danger")
        return redirect(url_for("private_area.dashboard"))

    if not title or len(title) > 160 or not description:
        flash("El título y la descripción son obligatorios.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if not lot_number or len(lot_number) > 40:
        flash("Ingresá un número de lote de hasta 40 caracteres.", "danger")
        return redirect(url_for("private_area.dashboard"))
    group = db.session.get(AuctionGroup, group_id) if group_id.isdigit() else None
    if group is None:
        flash("Creá un grupo de ventas y seleccionalo para el lote.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if sale_mode not in {"lot", "units"}:
        flash("Seleccioná si se vende como lote o por unidades.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if (
        not starting_price.is_finite()
        or starting_price <= 0
        or starting_price > MAX_PRICE
    ):
        flash("El precio base debe ser mayor que cero y no superar $U 9.999.999.999,99.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if (
        not commission_percent.is_finite()
        or commission_percent < 0
        or commission_percent > 100
    ):
        flash("La comisión debe estar entre 0% y 100%.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if quantity < 1 or quantity > 2147483647:
        flash("La cantidad debe ser un número entero positivo válido.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if duration_hours < 1 or duration_hours > 168:
        flash("La duración debe estar entre 1 y 168 horas (máximo 7 días).", "danger")
        return redirect(url_for("private_area.dashboard"))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if start_mode == "now":
        starts_at = now
    elif start_mode == "scheduled":
        try:
            local_start = datetime.strptime(
                request.form.get("starts_at", ""), "%Y-%m-%dT%H:%M"
            ).replace(tzinfo=ZoneInfo("America/Montevideo"))
        except ValueError:
            flash("Ingresá una fecha y hora de inicio válidas.", "danger")
            return redirect(url_for("private_area.dashboard"))
        starts_at = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        if starts_at <= now:
            flash("La fecha de inicio programada debe ser futura.", "danger")
            return redirect(url_for("private_area.dashboard"))
    else:
        flash("Indicá si la subasta comienza ahora o en una fecha programada.", "danger")
        return redirect(url_for("private_area.dashboard"))

    try:
        closes_at = starts_at + timedelta(hours=duration_hours)
    except (OverflowError, ValueError):
        flash("La duración ingresada supera el máximo admitido.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if closes_at <= starts_at:
        flash("La duración debe ser de al menos un segundo.", "danger")
        return redirect(url_for("private_area.dashboard"))

    duplicate_lot = Auction.query.filter_by(
        group_id=group.id, lot_number=lot_number
    ).first()
    if duplicate_lot:
        flash("Ese número de lote ya existe dentro del grupo seleccionado.", "danger")
        return redirect(url_for("private_area.dashboard"))

    featured_on_home = request.form.get("featured_on_home") == "on"
    if featured_on_home:
        feature_limit_message = _feature_limit_message(group.name, now)
        if feature_limit_message:
            flash(feature_limit_message, "danger")
            return redirect(url_for("private_area.dashboard"))

    photos = _uploaded_photos()
    if photos is None:
        return redirect(url_for("private_area.dashboard"))

    starting_price = starting_price.quantize(Decimal("0.01"))
    auction = Auction(
        title=title,
        description=description,
        lot_number=lot_number,
        group_name=group.name,
        sales_group=group,
        starting_price=starting_price,
        current_price=starting_price,
        commission_percent=commission_percent.quantize(Decimal("0.01")),
        quantity=quantity,
        sale_mode=sale_mode,
        featured_on_home=featured_on_home,
        starts_at=starts_at,
        closes_at=closes_at,
        photos=photos,
    )
    db.session.add(auction)
    db.session.commit()
    flash(f"El lote {lot_number} se publicó correctamente.", "success")
    return redirect(url_for("private_area.dashboard"))


@private_area_bp.route("/lotes/<int:auction_id>/editar", methods=["GET", "POST"])
@private_area_required
@csrf_protect
def edit_auction(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    has_history = bool(_lots_with_history([auction.id]))
    groups = AuctionGroup.query.order_by(AuctionGroup.name.asc()).all()
    now = datetime.now(timezone.utc)
    can_relaunch = not auction.is_active and not auction.is_upcoming
    relaunch_duration_hours = max(
        1,
        min(
            168,
            int(
                (
                    auction.closes_at.replace(tzinfo=None)
                    - auction.starts_at.replace(tzinfo=None)
                ).total_seconds()
                // 3600
            ),
        ),
    )
    relaunch_starts_at = (now + timedelta(minutes=2)).replace(
        second=0, microsecond=0
    )
    if request.method == "GET":
        return render_template(
            "private_auction_edit.html",
            auction=auction,
            groups=groups,
            has_history=has_history,
            can_relaunch=can_relaunch,
            relaunch_duration_hours=relaunch_duration_hours,
            relaunch_starts_at=relaunch_starts_at.astimezone(
                ZoneInfo("America/Montevideo")
            ).strftime("%Y-%m-%dT%H:%M"),
            relaunch_min_start=(now + timedelta(minutes=1))
            .astimezone(ZoneInfo("America/Montevideo"))
            .strftime("%Y-%m-%dT%H:%M"),
        )

    if request.form.get("action") == "relaunch":
        if not can_relaunch:
            flash("Solo se pueden relanzar lotes cuyo remate ya finalizó.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        lot_number = request.form.get("lot_number", "").strip()
        group_id = request.form.get("group_id", "").strip()
        sale_mode = request.form.get("sale_mode", "")
        start_mode = request.form.get("start_mode", "")
        try:
            starting_price = Decimal(
                request.form.get("starting_price", "").replace(",", ".")
            )
            commission_percent = Decimal(
                request.form.get("commission_percent", "").replace(",", ".")
            )
            quantity = int(request.form.get("quantity", ""))
            duration_hours = int(request.form.get("duration_hours", ""))
        except (InvalidOperation, ValueError):
            flash("Revisá los datos y la duración del nuevo remate.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        group = db.session.get(AuctionGroup, group_id) if group_id.isdigit() else None
        if not title or len(title) > 160 or not description:
            flash("El título y la descripción son obligatorios.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if not lot_number or len(lot_number) > 40:
            flash("Ingresá un número de lote de hasta 40 caracteres.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if group is None:
            flash("Seleccioná un grupo de ventas válido.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if sale_mode not in {"lot", "units"}:
            flash("Seleccioná si se vende como lote o por unidades.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if (
            not starting_price.is_finite()
            or starting_price <= 0
            or starting_price > MAX_PRICE
        ):
            flash("El precio base debe ser mayor que cero y no superar $U 9.999.999.999,99.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if (
            not commission_percent.is_finite()
            or commission_percent < 0
            or commission_percent > 100
        ):
            flash("La comisión debe estar entre 0% y 100%.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if quantity < 1 or quantity > 2147483647:
            flash("La cantidad debe ser un número entero positivo válido.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if duration_hours < 1 or duration_hours > 168:
            flash("La duración debe estar entre 1 y 168 horas (máximo 7 días).", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if start_mode == "now":
            starts_at_utc = now_utc
        elif start_mode == "scheduled":
            try:
                starts_at = datetime.strptime(
                    request.form.get("starts_at", ""), "%Y-%m-%dT%H:%M"
                ).replace(tzinfo=ZoneInfo("America/Montevideo"))
            except ValueError:
                flash("Ingresá una fecha y hora de inicio válidas.", "danger")
                return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
            starts_at_utc = starts_at.astimezone(timezone.utc).replace(tzinfo=None)
            if starts_at_utc <= now_utc:
                flash("La fecha programada debe ser futura.", "danger")
                return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        else:
            flash("Indicá si el nuevo remate comienza ahora o próximamente.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        closes_at_utc = starts_at_utc + timedelta(hours=duration_hours)

        duplicate_lot = Auction.query.filter(
            Auction.group_id == group.id,
            Auction.lot_number == lot_number,
            Auction.id != auction.id,
        ).first()
        if duplicate_lot:
            flash("Ese número de lote ya existe dentro del grupo seleccionado.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        photos = _uploaded_photos()
        if photos is None:
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        copied_photos = [
            AuctionImage(
                filename=photo.filename,
                content_type=photo.content_type,
                data=photo.data,
            )
            for photo in auction.photos
        ]
        relaunch = Auction(
            title=title,
            description=description,
            lot_number=lot_number,
            group_name=group.name,
            sales_group=group,
            starting_price=starting_price.quantize(Decimal("0.01")),
            current_price=starting_price.quantize(Decimal("0.01")),
            commission_percent=commission_percent.quantize(Decimal("0.01")),
            quantity=quantity,
            sale_mode=sale_mode,
            featured_on_home=False,
            starts_at=starts_at_utc,
            closes_at=closes_at_utc,
            photos=copied_photos + photos,
        )
        db.session.add(relaunch)
        db.session.commit()
        flash(f"El lote {lot_number} se publicó nuevamente en un nuevo remate.", "success")
        return redirect(url_for("private_area.dashboard"))

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if not title or len(title) > 160 or not description:
        flash("El título y la descripción son obligatorios.", "danger")
        return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

    if has_history:
        group = auction.sales_group
        lot_number = auction.lot_number
        starting_price = auction.starting_price
        commission_percent = auction.commission_percent
        quantity = auction.quantity
        sale_mode = auction.sale_mode
        starts_at = auction.starts_at
        closes_at = auction.closes_at
    else:
        lot_number = request.form.get("lot_number", "").strip()
        group_id = request.form.get("group_id", "").strip()
        sale_mode = request.form.get("sale_mode", "")
        try:
            starting_price = Decimal(
                request.form.get("starting_price", "").replace(",", ".")
            )
            commission_percent = Decimal(
                request.form.get("commission_percent", "").replace(",", ".")
            )
            quantity = int(request.form.get("quantity", ""))
        except (InvalidOperation, ValueError):
            flash("Revisá los valores de precio, comisión y cantidad.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        group = db.session.get(AuctionGroup, group_id) if group_id.isdigit() else None
        if not lot_number or len(lot_number) > 40:
            flash("Ingresá un número de lote de hasta 40 caracteres.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if group is None:
            flash("Seleccioná un grupo de ventas válido.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if sale_mode not in {"lot", "units"}:
            flash("Seleccioná si se vende como lote o por unidades.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if (
            not starting_price.is_finite()
            or starting_price <= 0
            or starting_price > MAX_PRICE
        ):
            flash("El precio base debe ser mayor que cero y no superar $U 9.999.999.999,99.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if (
            not commission_percent.is_finite()
            or commission_percent < 0
            or commission_percent > 100
        ):
            flash("La comisión debe estar entre 0% y 100%.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        if quantity < 1 or quantity > 2147483647:
            flash("La cantidad debe ser un número entero positivo válido.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        duplicate_lot = Auction.query.filter(
            Auction.group_id == group.id,
            Auction.lot_number == lot_number,
            Auction.id != auction.id,
        ).first()
        if duplicate_lot:
            flash("Ese número de lote ya existe dentro del grupo seleccionado.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

        original_start_value = auction.starts_at_montevideo.strftime("%Y-%m-%dT%H:%M")
        original_close_value = auction.closes_at_montevideo.strftime("%Y-%m-%dT%H:%M")
        submitted_start = request.form.get("starts_at", "")
        submitted_close = request.form.get("closes_at", "")
        try:
            starts_at = auction.starts_at
            if submitted_start != original_start_value:
                local_start = datetime.strptime(
                    submitted_start, "%Y-%m-%dT%H:%M"
                ).replace(tzinfo=ZoneInfo("America/Montevideo"))
                starts_at = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            closes_at = auction.closes_at
            if submitted_close != original_close_value:
                local_close = datetime.strptime(
                    submitted_close, "%Y-%m-%dT%H:%M"
                ).replace(tzinfo=ZoneInfo("America/Montevideo"))
                closes_at = local_close.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            flash("Ingresá fechas y horas de inicio y cierre válidas.", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
        duration = closes_at.replace(tzinfo=None) - starts_at.replace(tzinfo=None)
        if duration < timedelta(hours=1) or duration > timedelta(hours=168):
            flash("La duración debe estar entre 1 y 168 horas (máximo 7 días).", "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

    is_finished = auction.closes_at.replace(tzinfo=None) <= datetime.now(timezone.utc).replace(
        tzinfo=None
    )
    featured_on_home = (
        auction.featured_on_home
        if is_finished
        else request.form.get("featured_on_home") == "on"
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if featured_on_home and closes_at.replace(tzinfo=None) <= now:
        flash("No se puede destacar una subasta finalizada.", "danger")
        return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
    if featured_on_home and (
        not auction.featured_on_home or group.id != auction.group_id
    ):
        feature_limit_message = _feature_limit_message(group.name, now)
        if feature_limit_message:
            flash(feature_limit_message, "danger")
            return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

    try:
        removed_photo_ids = list(
            dict.fromkeys(int(value) for value in request.form.getlist("remove_photo_ids"))
        )
    except ValueError:
        flash("La selección de fotos no es válida.", "danger")
        return redirect(url_for("private_area.edit_auction", auction_id=auction.id))
    photos_by_id = {photo.id: photo for photo in auction.photos}
    if any(photo_id not in photos_by_id for photo_id in removed_photo_ids):
        flash("La selección contiene fotos que no pertenecen a este lote.", "danger")
        return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

    photos = _uploaded_photos()
    if photos is None:
        return redirect(url_for("private_area.edit_auction", auction_id=auction.id))

    auction.title = title
    auction.description = description
    auction.featured_on_home = featured_on_home
    if not has_history:
        auction.lot_number = lot_number
        auction.group_id = group.id
        auction.group_name = group.name
        auction.starting_price = starting_price.quantize(Decimal("0.01"))
        auction.current_price = auction.starting_price
        auction.commission_percent = commission_percent.quantize(Decimal("0.01"))
        auction.quantity = quantity
        auction.sale_mode = sale_mode
        if submitted_start != original_start_value:
            auction.starts_at = starts_at
        if submitted_close != original_close_value:
            auction.closes_at = closes_at
    for photo_id in removed_photo_ids:
        db.session.delete(photos_by_id[photo_id])
    auction.photos.extend(photos)
    db.session.commit()
    flash(f"El lote {auction.display_lot_number} se actualizó correctamente.", "success")
    return redirect(url_for("private_area.dashboard"))


@private_area_bp.post("/grupos")
@private_area_required
@csrf_protect
def create_group():
    name = request.form.get("name", "").strip()
    if not name or len(name) > 100:
        flash("Ingresá un nombre de grupo de hasta 100 caracteres.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if AuctionGroup.query.filter(func.lower(AuctionGroup.name) == name.lower()).first():
        flash("Ya existe un grupo con ese nombre.", "warning")
        return redirect(url_for("private_area.dashboard"))

    db.session.add(AuctionGroup(name=name))
    db.session.commit()
    flash(f"Se creó el grupo «{name}». Ya podés agregarle lotes.", "success")
    return redirect(url_for("private_area.dashboard"))


def _lots_with_history(auction_ids: list[int]) -> list[Auction]:
    if not auction_ids:
        return []
    ids_with_bids = {
        row[0]
        for row in db.session.query(Bid.auction_id)
        .filter(Bid.auction_id.in_(auction_ids))
        .distinct()
        .all()
    }
    ids_with_payments = {
        row[0]
        for row in db.session.query(AuctionPayment.auction_id)
        .filter(AuctionPayment.auction_id.in_(auction_ids))
        .all()
    }
    blocked_ids = ids_with_bids | ids_with_payments
    return [auction for auction in Auction.query.filter(Auction.id.in_(blocked_ids)).all()]


def _delete_auctions_without_history(auctions: list[Auction]) -> bool:
    blocked_lots = _lots_with_history([auction.id for auction in auctions])
    if blocked_lots:
        lot_numbers = ", ".join(auction.display_lot_number for auction in blocked_lots)
        flash(
            "No se pueden eliminar lotes que ya tienen pujas o pagos registrados. "
            f"Revisá: {lot_numbers}.",
            "danger",
        )
        return False
    for auction in auctions:
        db.session.delete(auction)
    return True


@private_area_bp.post("/grupos/<int:group_id>/eliminar")
@private_area_required
@csrf_protect
def delete_group(group_id: int):
    group = db.session.execute(
        db.select(AuctionGroup)
        .where(AuctionGroup.id == group_id)
        .with_for_update()
    ).scalar_one_or_none()
    if group is None:
        abort(404)
    auctions = (
        Auction.query.filter_by(group_id=group.id)
        .order_by(Auction.id.asc())
        .with_for_update()
        .all()
    )
    if not _delete_auctions_without_history(auctions):
        db.session.rollback()
        return redirect(url_for("private_area.dashboard"))
    group_name = group.name
    db.session.delete(group)
    db.session.commit()
    flash(f"Se eliminó el grupo «{group_name}» y sus lotes.", "success")
    return redirect(url_for("private_area.dashboard"))


@private_area_bp.post("/grupos/<int:group_id>/lotes/eliminar")
@private_area_required
@csrf_protect
def delete_group_auctions(group_id: int):
    group = db.session.get(AuctionGroup, group_id)
    if group is None:
        abort(404)
    raw_ids = request.form.getlist("auction_ids")
    try:
        auction_ids = list(dict.fromkeys(int(value) for value in raw_ids))
    except ValueError:
        flash("La selección de lotes no es válida.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if not auction_ids or any(auction_id <= 0 for auction_id in auction_ids):
        flash("Seleccioná uno o más lotes para eliminar.", "warning")
        return redirect(url_for("private_area.dashboard"))
    auctions = (
        Auction.query.filter(
            Auction.group_id == group.id,
            Auction.id.in_(auction_ids),
        )
        .order_by(Auction.id.asc())
        .with_for_update()
        .all()
    )
    if len(auctions) != len(auction_ids):
        flash("La selección contiene lotes que no pertenecen a este grupo.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if not _delete_auctions_without_history(auctions):
        db.session.rollback()
        return redirect(url_for("private_area.dashboard"))
    db.session.commit()
    flash(f"Se eliminaron {len(auctions)} lote(s) del grupo «{group.name}».", "success")
    return redirect(url_for("private_area.dashboard"))


@private_area_bp.post("/lotes/<int:auction_id>/portada")
@private_area_required
@csrf_protect
def update_home_feature(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    featured_on_home = request.form.get("featured_on_home") == "on"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if featured_on_home and auction.closes_at.replace(tzinfo=None) <= now:
        flash("No se puede destacar una subasta finalizada.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if featured_on_home and not auction.featured_on_home:
        feature_limit_message = _feature_limit_message(auction.group_name, now)
        if feature_limit_message:
            flash(feature_limit_message, "danger")
            return redirect(url_for("private_area.dashboard"))
    auction.featured_on_home = featured_on_home
    db.session.commit()
    flash("Se actualizó la selección de portada.", "success")
    return redirect(url_for("private_area.dashboard"))


@private_area_bp.get("/fotos/<int:photo_id>")
def photo(photo_id: int):
    image = db.get_or_404(AuctionImage, photo_id)
    return send_file(
        BytesIO(image.data),
        mimetype=image.content_type,
        download_name=image.filename,
        as_attachment=False,
        max_age=86400,
    )
