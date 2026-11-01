from datetime import datetime, timezone

from app.database import db


class Task(db.Model):
    """A minimal example model that can be extended for the project."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Task {self.title!r}>"
