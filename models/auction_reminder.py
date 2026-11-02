from datetime import datetime, timezone

from app.database import db


class AuctionReminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    auction = db.relationship("Auction", back_populates="reminders")
    user = db.relationship("User", back_populates="auction_reminders")

    __table_args__ = (
        db.UniqueConstraint("auction_id", "user_id", name="uq_auction_reminder_user"),
    )
