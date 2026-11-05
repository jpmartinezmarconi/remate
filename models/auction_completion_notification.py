from datetime import datetime, timezone

from app.database import db


class AuctionCompletionNotification(db.Model):
    __tablename__ = "auction_completion_notification"

    auction_id = db.Column(
        db.Integer,
        db.ForeignKey("auction.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sent_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    auction = db.relationship("Auction")
