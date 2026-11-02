from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hmac
from io import BytesIO
from functools import wraps
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
from werkzeug.utils import secure_filename

from app.database import db
from models.auction import Auction
from models.auction_image import AuctionImage
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
    photo_counts = dict(
        db.session.query(AuctionImage.auction_id, func.count(AuctionImage.id))
        .group_by(AuctionImage.auction_id)
        .all()
    )
    groups = [
        row[0]
        for row in db.session.query(Auction.group_name)
        .distinct()
        .order_by(Auction.group_name)
        .all()
    ]
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


@private_area_bp.post("/lotes")
@private_area_required
@csrf_protect
def create_auction():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    lot_number = request.form.get("lot_number", "").strip()
    group_name = request.form.get("group_name", "").strip() or "General"
    sale_mode = request.form.get("sale_mode", "")
    start_mode = request.form.get("start_mode", "")
    try:
        starting_price = Decimal(request.form.get("starting_price", "").replace(",", "."))
        commission_percent = Decimal(
            request.form.get("commission_percent", "0").replace(",", ".")
        )
        quantity = int(request.form.get("quantity", "1"))
        duration_hours = Decimal(
            request.form.get("duration_hours", "").replace(",", ".")
        )
    except (InvalidOperation, ValueError):
        flash("Revisá los valores de precio, comisión, cantidad y duración.", "danger")
        return redirect(url_for("private_area.dashboard"))

    if not title or len(title) > 160 or not description:
        flash("El título y la descripción son obligatorios.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if not lot_number or len(lot_number) > 40:
        flash("Ingresá un número de lote de hasta 40 caracteres.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if len(group_name) > 100:
        flash("El nombre del grupo puede tener hasta 100 caracteres.", "danger")
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
    if (
        not duration_hours.is_finite()
        or duration_hours <= 0
    ):
        flash("La duración debe ser mayor a cero.", "danger")
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
        closes_at = starts_at + timedelta(
            seconds=float(duration_hours * Decimal("3600"))
        )
    except (OverflowError, ValueError):
        flash("La duración ingresada supera el máximo admitido.", "danger")
        return redirect(url_for("private_area.dashboard"))
    if closes_at <= starts_at:
        flash("La duración debe ser de al menos un segundo.", "danger")
        return redirect(url_for("private_area.dashboard"))

    duplicate_lot = Auction.query.filter_by(
        group_name=group_name, lot_number=lot_number
    ).first()
    if duplicate_lot:
        flash("Ese número de lote ya existe dentro del grupo seleccionado.", "danger")
        return redirect(url_for("private_area.dashboard"))

    featured_on_home = request.form.get("featured_on_home") == "on"
    if featured_on_home:
        feature_limit_message = _feature_limit_message(group_name, now)
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
        group_name=group_name,
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
