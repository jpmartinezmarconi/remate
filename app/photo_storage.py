import hashlib
import uuid
from io import BytesIO
from urllib.parse import urlsplit
from urllib.request import urlopen

import click
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.database import db
from models.auction_image import AuctionImage


def _credentials():
    names = ("CLOUD_NAME_CLOUDINARY", "API_KEY_CLOUDINARY", "API_SECRET_CLOUDINARY")
    values = [(current_app.config.get(name) or "").strip() for name in names]
    if not all(values):
        raise ValueError("Falta configurar Cloudinary en el servicio.")
    return dict(zip(("cloud_name", "api_key", "api_secret"), values))


def upload_photo(data, public_id=None):
    credentials = _credentials()
    public_id = public_id or f"remate/photos/{uuid.uuid4().hex}"
    result = cloudinary.uploader.upload(
        BytesIO(data),
        public_id=public_id,
        resource_type="image",
        overwrite=False,
        timeout=30,
        **credentials,
    )
    url = result.get("secure_url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    expected_path = f"/{credentials['cloud_name']}/image/upload/"
    if (
        result.get("public_id") != public_id
        or parsed is None
        or parsed.scheme != "https"
        or parsed.netloc != "res.cloudinary.com"
        or not parsed.path.startswith(expected_path)
        or len(url) > 2048
    ):
        raise ValueError("Cloudinary devolvió una respuesta de imagen inválida.")
    return url, public_id


def discard_uploaded_photos(photos):
    for photo in photos:
        if not photo.cloud_public_id:
            continue
        try:
            result = cloudinary.uploader.destroy(
                photo.cloud_public_id, resource_type="image", timeout=30, **_credentials()
            )
            if result.get("result") not in {"ok", "not found"}:
                current_app.logger.error("No se pudo limpiar una foto subida a Cloudinary.")
        except (CloudinaryError, OSError, ValueError):
            current_app.logger.exception("No se pudo limpiar una foto subida a Cloudinary.")


def migrate_existing_photos():
    migrated = 0
    while True:
        photo = db.session.execute(
            db.select(AuctionImage)
            .where(AuctionImage.data.is_not(None))
            .order_by(AuctionImage.id)
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if photo is None:
            break
        data = photo.data
        digest = hashlib.sha256(data).hexdigest()
        public_id = f"remate/migrated/{photo.id}-{digest}"
        url, public_id = upload_photo(data, public_id)
        with urlopen(url, timeout=30) as response:
            remote_data = response.read(len(data) + 1)
        if hashlib.sha256(remote_data).hexdigest() != digest:
            raise ValueError(f"No se pudo verificar la foto {photo.id}; se conserva el original.")
        photo.cloud_url = url
        photo.cloud_public_id = public_id
        photo.data = None
        db.session.commit()
        migrated += 1
        click.echo(f"Foto {photo.id} migrada.")
    return migrated


def register_photo_commands(app):
    @app.cli.command("migrate-photos-to-cloudinary")
    def migrate_photos_command():
        try:
            count = migrate_existing_photos()
        except (CloudinaryError, OSError, ValueError, SQLAlchemyError) as exc:
            db.session.rollback()
            current_app.logger.exception("La migración de fotos a Cloudinary falló.")
            raise click.ClickException(
                "La migración se interrumpió; los originales pendientes se conservan. "
                "Revisá la configuración y los registros antes de reintentar."
            ) from exc
        click.echo(f"Fotos migradas en esta ejecución: {count}.")
