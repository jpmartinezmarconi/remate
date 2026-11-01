from .database import db


class ExampleRecord(db.Model):
    """Minimal SQLAlchemy model to extend for application data."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
