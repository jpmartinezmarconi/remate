from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from app.database import db
from models.auction import Auction
from models.auction_payment import AuctionPayment
from models.bid import Bid
from models.user import User
from .auth import login_required
from .security import csrf_protect


account_bp = Blueprint("account", __name__, url_prefix="/cuenta")
PAYMENT_METHODS = {
    "card": "Tarjeta de crédito o débito",
    "bank_transfer": "Transferencia bancaria",
    "mercadopago": "MercadoPago",
}


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


@account_bp.route("/subasta/<int:auction_id>/pagar", methods=["GET", "POST"])
@login_required
@csrf_protect
def pay_for_auction(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if auction.closes_at > now:
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
    if request.method == "POST":
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
        flash(
            "Registramos tu método de pago. El pago todavía está pendiente de confirmación.",
            "success",
        )
        return redirect(url_for("account.dashboard"))

    return render_template(
        "auction_payment.html",
        auction=auction,
        payment=payment,
        total=_winning_amount(auction),
        payment_methods=PAYMENT_METHODS,
        bank_transfer_instructions=current_app.config.get(
            "BANK_TRANSFER_INSTRUCTIONS", ""
        ),
    )
