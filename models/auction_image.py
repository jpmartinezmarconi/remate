from app.database import db


class AuctionImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id", ondelete="CASCADE"), nullable=False
    )
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(32), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)

    auction = db.relationship("Auction", back_populates="photos")
