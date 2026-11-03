from datetime import datetime, timezone

from app.database import db


class AuctionClosingReminder(db.Model):
    __tablename__ = "auction_closing_reminder"

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    sent_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "auction_id", "user_id", name="uq_auction_closing_reminder_user"
        ),
    )
