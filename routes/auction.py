from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
    session,
    url_for,
)
from sqlalchemy import func, or_
from urllib.parse import urlsplit

from app.database import db
from app.auction_reminders import send_due_auction_outbid_notifications
from app.email_notifications import send_business_notification
from models.auction import Auction
from models.auction_favorite import AuctionFavorite
from models.bid import Bid
from models.auction_image import AuctionImage
from models.auction_outbid_notification import AuctionOutbidNotification
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


def _leading_bid(auction_id: int) -> Bid | None:
    return (
        Bid.query.filter_by(auction_id=auction_id)
        .order_by(Bid.amount.desc(), Bid.id.desc())
        .first()
    )


def _saved_auction_ids(key: str) -> list[int]:
    values = session.get(key, [])
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(value for value in values if isinstance(value, int)))


def _favorite_auction_ids(user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    return {
        row[0]
        for row in db.session.query(AuctionFavorite.auction_id)
        .filter(AuctionFavorite.user_id == user_id)
        .all()
    }


def _recent_auctions() -> list[Auction]:
    now = utc_now_naive()
    auctions_by_id = {
        auction.id: auction
        for auction in Auction.query.filter(
            Auction.id.in_(_saved_auction_ids("recent_auction_ids")),
            Auction.closes_at > now,
        ).all()
    } if session.get("recent_auction_ids") else {}
    return [
        auctions_by_id[auction_id]
        for auction_id in _saved_auction_ids("recent_auction_ids")
        if auction_id in auctions_by_id
    ]


def _related_auctions(auction: Auction) -> list[Auction]:
    now = utc_now_naive()
    same_group = (
        Auction.query.filter(Auction.id != auction.id, Auction.closes_at > now)
        .filter(Auction.group_id == auction.group_id)
        .order_by(Auction.starts_at.asc(), Auction.closes_at.asc())
        .limit(4)
        .all()
    )
    if len(same_group) == 4:
        return same_group
    same_group_ids = [item.id for item in same_group]
    other_groups = (
        Auction.query.filter(
            Auction.id != auction.id,
            Auction.closes_at > now,
            Auction.group_id != auction.group_id,
        )
        .order_by(Auction.starts_at.asc(), Auction.closes_at.asc())
        .limit(4 - len(same_group))
        .all()
    )
    return same_group + [item for item in other_groups if item.id not in same_group_ids]


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
    hero_auctions = (
        Auction.query.filter(
            Auction.closes_at > now,
            or_(Auction.image_url.isnot(None), Auction.photos.any()),
        )
        .order_by(
            Auction.featured_on_home.desc(),
            Auction.starts_at.asc(),
            Auction.closes_at.asc(),
        )
        .limit(8)
        .all()
    )
    favorite_auction_ids = _favorite_auction_ids(
        g.current_user.id if g.current_user else None
    )
    favorite_auctions = (
        Auction.query.join(AuctionFavorite)
        .filter(
            AuctionFavorite.user_id == g.current_user.id,
            Auction.closes_at > now,
        )
        .order_by(AuctionFavorite.created_at.desc())
        .all()
        if g.current_user
        else []
    )
    recent_auctions = _recent_auctions()
    card_auctions = list({
        auction.id: auction
        for auction in auctions + hero_auctions + favorite_auctions + recent_auctions
    }.values())
    return render_template(
        "home.html",
        auctions=auctions,
        hero_auctions=hero_auctions,
        cover_photos=cover_photo_ids(card_auctions),
        favorite_auctions=favorite_auctions,
        favorite_auction_ids=favorite_auction_ids,
        recent_auctions=recent_auctions,
    )


@auction_bp.get("/subastas-activas")
def active_auctions():
    now = utc_now_naive()
    auctions = (
        Auction.query.filter(
            Auction.starts_at <= now,
            Auction.closes_at > now,
        )
        .order_by(Auction.group_name.asc(), Auction.closes_at.asc())
        .all()
    )
    sold_auctions = (
        Auction.query.filter(
            Auction.closes_at <= now,
            Auction.bids.any(),
        )
        .order_by(Auction.closes_at.desc(), Auction.id.desc())
        .all()
    )
    listed_auctions = auctions + sold_auctions
    return render_template(
        "active_auctions.html",
        auctions=auctions,
        sold_auctions=sold_auctions,
        cover_photos=cover_photo_ids(listed_auctions),
        favorite_auction_ids=_favorite_auction_ids(
            g.current_user.id if g.current_user else None
        ),
    )


@auction_bp.get("/articulos-en-remate")
@auction_bp.get("/proximas-subastas")
def upcoming_auctions():
    now = utc_now_naive()
    auctions = (
        Auction.query.filter(
            Auction.starts_at > now,
            Auction.closes_at > now,
        )
        .order_by(Auction.group_name.asc(), Auction.starts_at.asc())
        .all()
    )
    return render_template(
        "upcoming_auctions.html",
        auctions=auctions,
        cover_photos=cover_photo_ids(auctions),
        favorite_auction_ids=_favorite_auction_ids(
            g.current_user.id if g.current_user else None
        ),
    )


@auction_bp.get("/subasta/<int:auction_id>")
def detail(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    leading_bid = _leading_bid(auction.id)
    related_auctions = (
        _related_auctions(auction)
        if request.args.get("bid") == "success"
        else []
    )
    if auction.closes_at.replace(tzinfo=None) > utc_now_naive():
        recent_ids = [
            item_id
            for item_id in _saved_auction_ids("recent_auction_ids")
            if item_id != auction.id
        ]
        session["recent_auction_ids"] = (recent_ids + [auction.id])[-8:]
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
        leading_bid=leading_bid,
        reminder_subscribed=reminder_subscribed,
        is_favorite=(
            AuctionFavorite.query.filter_by(
                auction_id=auction.id,
                user_id=g.current_user.id,
            ).first()
            is not None
            if g.current_user
            else False
        ),
        favorite_auction_ids=_favorite_auction_ids(
            g.current_user.id if g.current_user else None
        ),
        related_auctions=related_auctions,
        cover_photos=cover_photo_ids(related_auctions),
        is_current_bidder=(
            leading_bid is not None and leading_bid.user_id == g.current_user.id
        ),
    )


@auction_bp.post("/subasta/<int:auction_id>/favorito")
@login_required
@csrf_protect
def toggle_favorite(auction_id: int):
    auction = db.get_or_404(Auction, auction_id)
    favorite = AuctionFavorite.query.filter_by(
        auction_id=auction.id,
        user_id=g.current_user.id,
    ).first()
    if favorite:
        db.session.delete(favorite)
        flash("Se quitó el artículo de tus favoritos.", "info")
    else:
        db.session.add(
            AuctionFavorite(auction_id=auction.id, user_id=g.current_user.id)
        )
        flash("Se agregó el artículo a tus favoritos.", "success")
    db.session.commit()

    return_to = request.form.get("return_to", "")
    parsed_return = urlsplit(return_to)
    if (
        return_to.startswith("/")
        and not return_to.startswith("//")
        and not parsed_return.netloc
        and not parsed_return.scheme
        and "\\" not in return_to
    ):
        return redirect(return_to)
    return redirect(url_for("auction.detail", auction_id=auction.id))


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

    previous_leading_bid = _leading_bid(auction.id)
    if (
        previous_leading_bid
        and previous_leading_bid.user_id == g.current_user.id
    ):
        flash(
            "Tu oferta ya es la más alta. Podés volver a ofertar cuando otro "
            "participante la supere.",
            "warning",
        )
        return redirect(url_for("auction.detail", auction_id=auction.id))

    current_price = Decimal(auction.current_price)
    if previous_leading_bid is None:
        try:
            amount = Decimal(request.form.get("amount", "").replace(",", "."))
            if not amount.is_finite():
                raise InvalidOperation
            amount = amount.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            flash("Ingresá un monto válido.", "danger")
            return redirect(url_for("auction.detail", auction_id=auction.id))
        if amount < Decimal(auction.starting_price):
            flash(
                f"La primera oferta no puede ser menor que el precio base "
                f"de $U {auction.starting_price:,.2f}.",
                "danger",
            )
            return redirect(url_for("auction.detail", auction_id=auction.id))
    else:
        if request.form.get("expected_bid_id") != str(previous_leading_bid.id):
            flash(
                "La oferta cambió. Revisá el nuevo importe antes de ofertar.",
                "warning",
            )
            return redirect(url_for("auction.detail", auction_id=auction.id))
        amount = current_price + minimum_bid_increment(current_price)

    if amount > Decimal("9999999999.99"):
        flash("La oferta supera el importe máximo permitido.", "danger")
        return redirect(url_for("auction.detail", auction_id=auction.id))

    # The conditional update protects SQLite as well as databases with row locks.
    conditions = [
        Auction.id == auction.id,
        Auction.current_price == current_price,
        Auction.starts_at <= utc_now_naive(),
        Auction.closes_at > utc_now_naive(),
    ]
    if previous_leading_bid is None:
        conditions.append(~Auction.bids.any())
    updated = db.session.execute(
        db.update(Auction).where(*conditions).values(current_price=amount)
    )
    if updated.rowcount != 1:
        db.session.rollback()
        flash("La oferta cambió o la subasta cerró. Revisá el lote nuevamente.", "warning")
        return redirect(url_for("auction.detail", auction_id=auction_id))

    bid = Bid(amount=amount, auction=auction, bidder=g.current_user)
    db.session.add(bid)
    outbid_notification = None
    if (
        previous_leading_bid
        and previous_leading_bid.user_id != g.current_user.id
    ):
        outbid_notification = AuctionOutbidNotification(
            outbid_bid=previous_leading_bid,
            replacement_bid=bid,
        )
        db.session.add(outbid_notification)
    db.session.commit()
    if outbid_notification is not None:
        try:
            send_due_auction_outbid_notifications(outbid_notification.id)
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Immediate outbid notification failed; it remains pending for retry."
            )
    try:
        send_business_notification(
            "Nueva puja recibida · Remate Martínez",
            f"Se recibió una nueva puja.\n\n"
            f"Lote: {auction.display_lot_number} · {auction.title}\n"
            f"Participante: {g.current_user.full_name or g.current_user.username}\n"
            f"Correo: {g.current_user.email}\n"
            f"Oferta: $U {amount:,.2f}\n",
        )
    except (OSError, RuntimeError, smtplib.SMTPException, ValueError):
        current_app.logger.exception(
            "Could not send the new-bid notification for auction %s.", auction.id
        )
    flash("¡Oferta registrada! Ahora sos quien va ganando.", "success")
    return redirect(url_for("auction.detail", auction_id=auction.id, bid="success"))
