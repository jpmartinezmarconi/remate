from datetime import datetime, timezone

from app.database import db


class AuctionFavorite(db.Model):
    __tablename__ = "auction_favorite"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id", ondelete="CASCADE"), nullable=False
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    auction = db.relationship("Auction")

    __table_args__ = (
        db.UniqueConstraint("user_id", "auction_id", name="uq_auction_favorite_user"),
    )
