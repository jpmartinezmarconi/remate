from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func

from app.database import db
from models.auction import Auction
from models.bid import Bid
from models.auction_image import AuctionImage
from models.auction_reminder import AuctionReminder
from .auth import login_required
from .security import csrf_protect


auction_bp = Blueprint("auction", __name__)


def utc_now_naive() -> datetime:
    """Use UTC timestamps compatible with both PostgreSQL and SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def cover_photo_ids(auctions: list[Auction]) -> dict[int, int]:
    auction_ids = [auction.id for auction in auctions]
    if not auction_ids:
        return {}
    rows = (
        db.session.query(AuctionImage.auction_id, func.min(AuctionImage.id))
        .filter(AuctionImage.auction_id.in_(auction_ids))
        .group_by(AuctionImage.auction_id)
        .all()
    )
    return {auction_id: photo_id for auction_id, photo_id in rows}


def minimum_bid_increment(current_price: Decimal) -> Decimal:
    if current_price <= Decimal("500"):
        return Decimal("50")
    if current_price <= Decimal("2000"):
        return Decimal("100")
    if current_price <= Decimal("10000"):
        return Decimal("500")
    return Decimal("1000")


@auction_bp.get("/")
def home():
    now = utc_now_naive()
    auctions = (
        Auction.query.filter(
            Auction.closes_at > now,
            Auction.featured_on_home.is_(True),
        )
        .order_by(Auction.group_name.asc(), Auction.closes_at.asc())
        .all()
    )
    return render_template(
        "home.html", auctions=auctions, cover_photos=cover_photo_ids(auctions)
    )


@auction_bp.get("/subastas-activas")
def active_auctions():
    now = utc_now_naive()
    auctions = (
        Auction.query.filter(Auction.closes_at > now)
        .order_by(Auction.group_name.asc(), Auction.starts_at.asc(), Auction.closes_at.asc())
        .all()
    )
    return render_template(
        "active_auctions.html",
        auctions=auctions,
        cover_photos=cover_photo_ids(auctions),
    )


@auction_bp.get("/subasta/<int:auction_id>")
def detail(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    reminder_subscribed = False
    if g.current_user and auction.is_upcoming:
        reminder_subscribed = (
            AuctionReminder.query.filter_by(
                auction_id=auction.id,
                user_id=g.current_user.id,
            ).first()
            is not None
        )
    return render_template(
        "auction_detail.html",
        auction=auction,
        reminder_subscribed=reminder_subscribed,
    )


@auction_bp.post("/subasta/<int:auction_id>/notificar")
@login_required
@csrf_protect
def toggle_auction_reminder(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    if not auction.is_upcoming:
        flash("Los avisos están disponibles para subastas próximas.", "warning")
        return redirect(url_for("auction.detail", auction_id=auction.id))

    reminder = AuctionReminder.query.filter_by(
        auction_id=auction.id,
        user_id=g.current_user.id,
    ).first()
    if reminder:
        db.session.delete(reminder)
        db.session.commit()
        flash("Se canceló el aviso por correo.", "info")
    else:
        reminder = AuctionReminder(auction=auction, user=g.current_user)
        db.session.add(reminder)
        db.session.commit()
        flash(
            "Te enviaremos un correo 24 horas antes del inicio. "
            "Si te suscribís dentro de las últimas 24 horas, lo enviaremos "
            "en el próximo ciclo de avisos.",
            "success",
        )
    return redirect(url_for("auction.detail", auction_id=auction.id))


@auction_bp.post("/subasta/<int:auction_id>/ofertar")
@login_required
@csrf_protect
def place_bid(auction_id: int):
    if not g.current_user.profile_complete:
        flash("Completá tus datos personales y de envío antes de ofertar.", "warning")
        return redirect(url_for("account.dashboard"))
    auction = db.session.execute(
        db.select(Auction)
        .where(Auction.id == auction_id)
        .with_for_update()
    ).scalar_one_or_none()
    if auction is None:
        abort(404)
    if auction.closes_at.replace(tzinfo=None) <= utc_now_naive():
        flash("Esta subasta ya cerró y no acepta más ofertas.", "warning")
        return redirect(url_for("auction.detail", auction_id=auction.id))
    if auction.starts_at.replace(tzinfo=None) > utc_now_naive():
        flash("Esta subasta todavía no comenzó.", "warning")
        return redirect(url_for("auction.detail", auction_id=auction.id))

    try:
        amount = Decimal(request.form.get("amount", "").replace(",", "."))
        if not amount.is_finite():
            raise InvalidOperation
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        flash("Ingresá un monto válido.", "danger")
        return redirect(url_for("auction.detail", auction_id=auction.id))

    if amount <= Decimal(auction.current_price):
        flash("Tu oferta no puede ser menor o igual a la oferta actual.", "danger")
        return redirect(url_for("auction.detail", auction_id=auction.id))
    current_price = Decimal(auction.current_price)
    bid_increment = minimum_bid_increment(current_price)
    amount_above_current = amount - current_price
    valid_steps = max(
        1,
        int(
            (amount_above_current / bid_increment).to_integral_value(
                rounding=ROUND_CEILING
            )
        ),
    )
    next_valid_offer = current_price + bid_increment * valid_steps
    if amount_above_current < bid_increment or amount_above_current % bid_increment:
        flash(
            f"La próxima oferta válida es $U {next_valid_offer:,.2f}; "
            f"las pujas avanzan en saltos de $U {bid_increment:,.2f}.",
            "danger",
        )
        return redirect(url_for("auction.detail", auction_id=auction.id))

    bid = Bid(amount=amount, auction=auction, bidder=g.current_user)
    auction.current_price = amount
    db.session.add(bid)
    db.session.commit()
    flash("¡Oferta registrada! Ahora sos quien va ganando.", "success")
    return redirect(url_for("auction.detail", auction_id=auction.id))
