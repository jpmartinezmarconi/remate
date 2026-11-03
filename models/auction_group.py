from datetime import datetime, timezone

from app.database import db


class AuctionGroup(db.Model):
    __tablename__ = "auction_group"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    auctions = db.relationship(
        "Auction",
        back_populates="sales_group",
        cascade="all, delete-orphan",
    )
