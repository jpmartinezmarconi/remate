from datetime import datetime, timezone

from app.database import db


class Bid(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    auction_id = db.Column(db.Integer, db.ForeignKey("auction.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    auction = db.relationship("Auction", back_populates="bids")
    bidder = db.relationship("User", back_populates="bids")
