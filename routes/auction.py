from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.database import db
from models.auction import Auction
from models.bid import Bid
from .auth import login_required
from .security import csrf_protect


auction_bp = Blueprint("auction", __name__)


def utc_now_naive() -> datetime:
    """Use UTC timestamps compatible with both PostgreSQL and SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@auction_bp.get("/")
def home():
    now = utc_now_naive()
    auctions = (
        Auction.query.filter(Auction.closes_at > now)
        .order_by(Auction.closes_at.asc())
        .all()
    )
    return render_template("home.html", auctions=auctions)


@auction_bp.get("/subasta/<int:auction_id>")
def detail(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    return render_template("auction_detail.html", auction=auction)


@auction_bp.post("/subasta/<int:auction_id>/ofertar")
@login_required
@csrf_protect
def place_bid(auction_id: int):
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

    try:
        amount = Decimal(request.form.get("amount", "").replace(",", "."))
        if not amount.is_finite():
            raise InvalidOperation
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        flash("Ingresá un monto válido.", "danger")
        return redirect(url_for("auction.detail", auction_id=auction.id))

    if amount <= Decimal(auction.current_price):
        flash(
            f"Tu oferta debe superar el precio actual de ${auction.current_price:,.2f}.",
            "danger",
        )
        return redirect(url_for("auction.detail", auction_id=auction.id))

    bid = Bid(amount=amount, auction=auction, bidder=g.current_user)
    auction.current_price = amount
    db.session.add(bid)
    db.session.commit()
    flash("¡Oferta registrada! Ahora sos quien va ganando.", "success")
    return redirect(url_for("auction.detail", auction_id=auction.id))
