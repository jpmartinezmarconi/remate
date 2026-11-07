from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import secrets
import smtplib

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.database import db
from app.email_notifications import send_business_notification
from models.auction import Auction
from models.auction_payment import AuctionPayment
from models.bid import Bid
from models.user import User
from .auth import login_required
from .security import csrf_protect


account_bp = Blueprint("account", __name__, url_prefix="/cuenta")
PAYMENT_METHODS = {
    "brou_transfer": "Transferencia bancaria BROU",
    "mi_dinero": "Mi Dinero / Red Pagos",
}
PAYMENT_PORTALS = {
    "brou_transfer": "https://www.ebanking.brou.com.uy/frontend/",
    "mi_dinero": "https://webapp.midinero.com.uy/",
}
TELEGRAM_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")


def _profile_values() -> dict[str, str]:
    return {
        "full_name": request.form.get("full_name", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "phone": request.form.get("phone", "").strip(),
        "shipping_address": request.form.get("shipping_address", "").strip(),
        "city": request.form.get("city", "").strip(),
        "postal_code": request.form.get("postal_code", "").strip(),
    }


def _profile_error(values: dict[str, str]) -> str | None:
    limits = {
        "full_name": 160,
        "email": 255,
        "phone": 40,
        "shipping_address": 255,
        "city": 100,
        "postal_code": 20,
    }
    labels = {
        "full_name": "El nombre completo",
        "email": "El correo electrónico",
        "phone": "El teléfono",
        "shipping_address": "La dirección de envío",
        "city": "La ciudad",
        "postal_code": "El código postal",
    }
    for field, value in values.items():
        if not value:
            return f"{labels[field]} es obligatorio."
        if len(value) > limits[field]:
            return f"{labels[field]} supera el máximo de {limits[field]} caracteres."
    if "@" not in values["email"] or "." not in values["email"].rsplit("@", 1)[-1]:
        return "Ingresá un correo electrónico válido."
    return None


def _winning_amount(auction: Auction) -> Decimal:
    winning_bid = (
        Bid.query.filter_by(auction_id=auction.id)
        .order_by(Bid.amount.desc(), Bid.created_at.asc(), Bid.id.asc())
        .first()
    )
    if winning_bid is None:
        raise ValueError("An auction without bids has no winning bid.")
    multiplier = auction.quantity if auction.sale_mode == "units" else 1
    hammer_total = Decimal(winning_bid.amount) * multiplier
    return (
        hammer_total
        * (Decimal("1") + Decimal(auction.commission_percent) / Decimal("100"))
    ).quantize(Decimal("0.01"))


@account_bp.get("")
@login_required
def dashboard():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    bid_rows = (
        Bid.query.join(Auction)
        .filter(Bid.user_id == g.current_user.id)
        .order_by(Bid.created_at.desc(), Bid.id.desc())
        .all()
    )
    participated_by_id = {}
    for bid in bid_rows:
        participated_by_id.setdefault(bid.auction_id, bid.auction)
    participated = list(participated_by_id.values())

    closed_bids = (
        Bid.query.join(Auction)
        .filter(Auction.closes_at <= now)
        .order_by(
            Bid.auction_id.asc(),
            Bid.amount.desc(),
            Bid.created_at.asc(),
            Bid.id.asc(),
        )
        .all()
    )
    winners = {}
    for bid in closed_bids:
        winners.setdefault(bid.auction_id, bid)
    won_auctions = [
        bid.auction for bid in winners.values() if bid.user_id == g.current_user.id
    ]
    won_auctions.sort(key=lambda auction: auction.closes_at, reverse=True)
    payments = {}
    if won_auctions:
        payments = {
            payment.auction_id: payment
            for payment in AuctionPayment.query.filter(
                AuctionPayment.user_id == g.current_user.id,
                AuctionPayment.auction_id.in_(
                    [auction.id for auction in won_auctions]
                ),
            ).all()
        }
    payment_totals = {
        auction.id: _winning_amount(auction) for auction in won_auctions
    }
    return render_template(
        "account_dashboard.html",
        user=g.current_user,
        participated=participated,
        won_auctions=won_auctions,
        payments=payments,
        payment_totals=payment_totals,
        telegram_enabled=bool(current_app.config.get("TELEGRAM_BOT_TOKEN")),
    )


@account_bp.post("/perfil")
@login_required
@csrf_protect
def update_profile():
    values = _profile_values()
    error = _profile_error(values)
    if error:
        flash(error, "danger")
        return redirect(url_for("account.dashboard"))
    existing_user = User.query.filter(
        User.email == values["email"],
        User.id != g.current_user.id,
    ).first()
    if existing_user:
        flash("Ese correo electrónico ya está asociado a otra cuenta.", "danger")
        return redirect(url_for("account.dashboard"))

    for field, value in values.items():
        setattr(g.current_user, field, value)
    db.session.commit()
    flash("Tus datos se actualizaron correctamente.", "success")
    return redirect(url_for("account.dashboard"))


@account_bp.post("/telegram/vincular")
@login_required
@csrf_protect
def link_telegram():
    if not current_app.config.get("TELEGRAM_BOT_TOKEN"):
        flash("La vinculación con Telegram no está disponible por el momento.", "warning")
        return redirect(url_for("account.dashboard"))
    if g.current_user.telegram_chat_id:
        flash("Tu cuenta ya está vinculada con Telegram.", "info")
        return redirect(url_for("account.dashboard"))

    username = current_app.config.get("TELEGRAM_BOT_USERNAME", "rematemartinezbot")
    if not isinstance(username, str) or not TELEGRAM_USERNAME_PATTERN.fullmatch(username):
        current_app.logger.error("TELEGRAM_BOT_USERNAME is invalid.")
        flash("No se pudo iniciar la vinculación con Telegram.", "danger")
        return redirect(url_for("account.dashboard"))

    token = secrets.token_urlsafe(24)
    g.current_user.telegram_link_token = token
    g.current_user.telegram_link_token_expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    db.session.commit()
    return redirect(f"https://t.me/{username}?start={token}")


@account_bp.post("/telegram/desvincular")
@login_required
@csrf_protect
def unlink_telegram():
    g.current_user.telegram_chat_id = None
    g.current_user.telegram_link_token = None
    g.current_user.telegram_link_token_expires_at = None
    db.session.commit()
    flash("Se desvinculó tu cuenta de Telegram.", "success")
    return redirect(url_for("account.dashboard"))


@account_bp.route("/subasta/<int:auction_id>/pagar", methods=["GET", "POST"])
@login_required
@csrf_protect
def pay_for_auction(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    if request.method == "POST":
        auction = db.session.execute(
            db.select(Auction).where(Auction.id == auction_id).with_for_update()
        ).scalar_one_or_none()
        if auction is None:
            abort(404)
    closes_at = auction.closes_at
    if closes_at.tzinfo is None:
        closes_at = closes_at.replace(tzinfo=timezone.utc)
    if closes_at > datetime.now(timezone.utc):
        abort(404)
    top_bid = (
        Bid.query.filter_by(auction_id=auction.id)
        .order_by(Bid.amount.desc(), Bid.created_at.asc(), Bid.id.asc())
        .first()
    )
    if top_bid is None or top_bid.user_id != g.current_user.id:
        abort(403)
    if not g.current_user.profile_complete:
        flash("Completá tus datos de contacto y envío antes de continuar.", "warning")
        return redirect(url_for("account.dashboard"))

    payment = AuctionPayment.query.filter_by(auction_id=auction.id).first()
    if payment and payment.status == "paid":
        flash("Este lote ya figura como pagado.", "info")
        return redirect(url_for("account.dashboard"))
    if request.method == "POST":
        is_new_payment = payment is None
        method = request.form.get("method", "")
        if method not in PAYMENT_METHODS:
            flash("Seleccioná un método de pago válido.", "danger")
            return redirect(url_for("account.pay_for_auction", auction_id=auction.id))
        total = _winning_amount(auction)
        if payment is None:
            payment = AuctionPayment(
                auction=auction,
                user=g.current_user,
                method=method,
                amount=total,
                status="pending",
            )
            db.session.add(payment)
        else:
            payment.method = method
            payment.amount = total
            payment.status = "pending"
            payment.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        if is_new_payment:
            try:
                send_business_notification(
                    "Nueva compra registrada · Remate Martínez",
                    f"El ganador registró un método de pago; queda pendiente de "
                    f"confirmación.\n\n"
                    f"Lote: {auction.display_lot_number} · {auction.title}\n"
                    f"Comprador: {g.current_user.full_name or g.current_user.username}\n"
                    f"Correo: {g.current_user.email}\n"
                    f"Método de pago: {PAYMENT_METHODS[method]}\n"
                    f"Total: $U {total:,.2f}\n",
                )
            except (OSError, RuntimeError, smtplib.SMTPException, ValueError):
                current_app.logger.exception(
                    "Could not send the purchase notification for auction %s.",
                    auction.id,
                )
        return redirect(PAYMENT_PORTALS[method], code=303)

    return render_template(
        "auction_payment.html",
        auction=auction,
        payment=payment,
        total=_winning_amount(auction),
        payment_methods=PAYMENT_METHODS,
    )
