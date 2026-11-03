from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

from app.database import db


class Auction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    lot_number = db.Column(db.String(40), nullable=True)
    starting_price = db.Column(db.Numeric(12, 2), nullable=False)
    current_price = db.Column(db.Numeric(12, 2), nullable=False)
    commission_percent = db.Column(db.Numeric(5, 2), nullable=False, default=20)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    sale_mode = db.Column(db.String(12), nullable=False, default="lot")
    group_name = db.Column(db.String(100), nullable=False, default="General")
    group_id = db.Column(
        db.Integer, db.ForeignKey("auction_group.id"), nullable=False, index=True
    )
    featured_on_home = db.Column(db.Boolean, nullable=False, default=False)
    starts_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    closes_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    seller = db.relationship("User", back_populates="auctions")
    sales_group = db.relationship("AuctionGroup", back_populates="auctions")
    bids = db.relationship(
        "Bid", back_populates="auction", cascade="all, delete-orphan", lazy="select"
    )
    photos = db.relationship(
        "AuctionImage",
        back_populates="auction",
        cascade="all, delete-orphan",
        order_by="AuctionImage.id",
        lazy="select",
    )
    reminders = db.relationship(
        "AuctionReminder",
        back_populates="auction",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def is_active(self) -> bool:
        now = datetime.now(timezone.utc)
        starts_at = self.starts_at
        closes_at = self.closes_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        if closes_at.tzinfo is None:
            closes_at = closes_at.replace(tzinfo=timezone.utc)
        return starts_at <= now < closes_at

    @property
    def is_upcoming(self) -> bool:
        starts_at = self.starts_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        closes_at = self.closes_at
        if closes_at.tzinfo is None:
            closes_at = closes_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return starts_at > now and closes_at > now

    @property
    def starts_at_montevideo(self) -> datetime:
        starts_at = self.starts_at
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        return starts_at.astimezone(ZoneInfo("America/Montevideo"))

    @property
    def closes_at_montevideo(self) -> datetime:
        closes_at = self.closes_at
        if closes_at.tzinfo is None:
            closes_at = closes_at.replace(tzinfo=timezone.utc)
        return closes_at.astimezone(ZoneInfo("America/Montevideo"))

    @property
    def bid_count(self) -> int:
        return len(self.bids)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.starting_price is not None and self.current_price is None:
            self.current_price = Decimal(self.starting_price)

    @property
    def display_lot_number(self) -> str:
        return self.lot_number or f"{self.id:04d}"
