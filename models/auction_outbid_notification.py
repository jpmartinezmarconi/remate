from app.database import db


class AuctionOutbidNotification(db.Model):
    __tablename__ = "auction_outbid_notification"

    id = db.Column(db.Integer, primary_key=True)
    outbid_bid_id = db.Column(
        db.Integer,
        db.ForeignKey("bid.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    replacement_bid_id = db.Column(
        db.Integer, db.ForeignKey("bid.id", ondelete="CASCADE"), nullable=False
    )
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    telegram_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)

    outbid_bid = db.relationship("Bid", foreign_keys=[outbid_bid_id])
    replacement_bid = db.relationship("Bid", foreign_keys=[replacement_bid_id])
