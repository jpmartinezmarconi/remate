from datetime import datetime, timezone

from app.database import db


class AuctionPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    method = db.Column(db.String(24), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="pending")
    amount = db.Column(db.Numeric(22, 2), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    auction = db.relationship("Auction")
    user = db.relationship("User", back_populates="payments")

    __table_args__ = (
        db.UniqueConstraint("auction_id", name="uq_auction_payment_auction"),
    )
