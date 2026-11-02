from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from app.database import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(160), nullable=False, default="")
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(40), nullable=False, default="")
    shipping_address = db.Column(db.String(255), nullable=False, default="")
    city = db.Column(db.String(100), nullable=False, default="")
    postal_code = db.Column(db.String(20), nullable=False, default="")
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    auctions = db.relationship("Auction", back_populates="seller", lazy="select")
    bids = db.relationship("Bid", back_populates="bidder", lazy="select")
    auction_reminders = db.relationship(
        "AuctionReminder",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    payments = db.relationship(
        "AuctionPayment",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def profile_complete(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.full_name,
                self.phone,
                self.shipping_address,
                self.city,
                self.postal_code,
                self.email,
            )
        )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
