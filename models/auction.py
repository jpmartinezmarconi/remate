from datetime import datetime, timezone
from decimal import Decimal

from app.database import db


class Auction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    starting_price = db.Column(db.Numeric(12, 2), nullable=False)
    current_price = db.Column(db.Numeric(12, 2), nullable=False)
    closes_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    seller = db.relationship("User", back_populates="auctions")
    bids = db.relationship(
        "Bid", back_populates="auction", cascade="all, delete-orphan", lazy="select"
    )

    @property
    def is_active(self) -> bool:
        closes_at = self.closes_at
        if closes_at.tzinfo is None:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            now = datetime.now(timezone.utc)
        return closes_at > now

    @property
    def bid_count(self) -> int:
        return len(self.bids)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.starting_price is not None and self.current_price is None:
            self.current_price = Decimal(self.starting_price)
