import re
import unicodedata

from flask import Blueprint, jsonify, request, url_for

from app.database import db
from models.auction import Auction
from .auction import utc_now_naive


help_bp = Blueprint("help", __name__, url_prefix="/api/ayuda")
MAX_QUESTION_LENGTH = 300
MAX_AUCTIONS_IN_REPLY = 8
PHONE = "096 164 645"
EMAIL = "info@rematemartinez.com.uy"
ADDRESS = "Av. 8 de Octubre 4336/4328, Montevideo, Uruguay"


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _public_auctions(*, upcoming: bool) -> list[Auction]:
    now = utc_now_naive()
    query = Auction.query.filter(Auction.closes_at > now)
    if upcoming:
        query = query.filter(Auction.starts_at > now)
    else:
        query = query.filter(Auction.starts_at <= now)
    return query.order_by(Auction.starts_at.asc(), Auction.closes_at.asc()).all()


def _auction_summary(auction: Auction) -> str:
    now = utc_now_naive()
    if auction.closes_at.replace(tzinfo=None) <= now:
        status = "Finalizada"
    elif auction.starts_at.replace(tzinfo=None) > now:
        status = "Próximamente"
    else:
        status = "Activa"
    details = [
        f"Lote {auction.display_lot_number}: {auction.title} ({status}).",
    ]
    if auction.is_upcoming:
        details.append(
            "Comienza el "
            f"{auction.starts_at_montevideo.strftime('%d/%m/%Y a las %H:%M')} "
            "h, hora de Uruguay."
        )
    else:
        details.append(
            "Finaliza el "
            f"{auction.closes_at_montevideo.strftime('%d/%m/%Y a las %H:%M')} "
            "h, hora de Uruguay."
        )
    price_label = (
        "Oferta actual"
        if auction.current_price > auction.starting_price
        else "Precio base"
    )
    details.append(f"{price_label}: $U {auction.current_price:,.2f}.")
    if auction.sale_mode == "units":
        details.append(f"Oferta por unidad; cantidad: {auction.quantity}.")
    else:
        details.append("La oferta corresponde al lote completo.")
    details.append(f"Comisión de este lote: {auction.commission_percent}%.")
    return " ".join(details)


def _auction_link(auction: Auction) -> dict[str, str]:
    return {
        "label": f"Ver lote {auction.display_lot_number}",
        "url": url_for("auction.detail", auction_id=auction.id),
    }


def _find_auction(question: str) -> Auction | None:
    normalized_question = _normalize(question)
    auctions = db.session.query(Auction.id, Auction.title, Auction.lot_number).all()
    for auction_id, _, lot_number in auctions:
        displayed_number = _normalize(lot_number or f"{auction_id:04d}")
        if re.search(rf"(?<![\w]){re.escape(displayed_number)}(?![\w])", normalized_question):
            return db.session.get(Auction, auction_id)

    searchable_question = re.sub(r"[^a-z0-9]+", " ", normalized_question).strip()
    if len(searchable_question) < 3:
        return None
    question_words = set(searchable_question.split())
    title_matches = []
    for auction_id, title, _ in auctions:
        title = re.sub(r"[^a-z0-9]+", " ", _normalize(title)).strip()
        if title and title in searchable_question:
            return db.session.get(Auction, auction_id)
        title_words = {word for word in title.split() if len(word) >= 4}
        if title_words & question_words:
            title_matches.append(auction_id)
    if len(title_matches) == 1:
        return db.session.get(Auction, title_matches[0])
    return None


def _answer(question: str) -> tuple[str, list[dict[str, str]]]:
    normalized_question = _normalize(question)
    auction = _find_auction(question)
    if auction:
        now = utc_now_naive()
        if auction.closes_at.replace(tzinfo=None) <= now:
            status = "finalizó"
        elif auction.starts_at.replace(tzinfo=None) > now:
            status = "aún no comenzó"
        else:
            status = "está activa"
        return (
            f"{_auction_summary(auction)} El lote {status}. "
            "Revisá la ficha para ver el estado y los detalles actualizados.",
            [_auction_link(auction)],
        )

    if any(term in normalized_question for term in ("proxima", "proximo", "futura", "por comenzar", "cuando empieza")):
        auctions = _public_auctions(upcoming=True)
        if not auctions:
            return "Por el momento no hay subastas próximas publicadas. Revisá nuevamente más adelante.", [
                {"label": "Ver próximas subastas", "url": url_for("auction.upcoming_auctions")}
            ]
        visible = auctions[:MAX_AUCTIONS_IN_REPLY]
        reply = "Próximas subastas:\n" + "\n".join(
            _auction_summary(item) for item in visible
        )
        if len(auctions) > len(visible):
            reply += f"\nHay {len(auctions) - len(visible)} lotes próximos más."
        return reply, [
            {"label": "Ver próximas subastas", "url": url_for("auction.upcoming_auctions")}
        ] + [_auction_link(item) for item in visible]

    if any(term in normalized_question for term in ("activa", "activas", "activo", "activos", "en curso", "ahora", "actualmente", "disponible", "numero de lote", "subastas")):
        auctions = _public_auctions(upcoming=False)
        if not auctions:
            return "Ahora no hay subastas activas. Podés consultar las que comenzarán próximamente.", [
                {"label": "Ver próximas subastas", "url": url_for("auction.upcoming_auctions")}
            ]
        visible = auctions[:MAX_AUCTIONS_IN_REPLY]
        reply = "Subastas activas:\n" + "\n".join(
            _auction_summary(item) for item in visible
        )
        if len(auctions) > len(visible):
            reply += f"\nHay {len(auctions) - len(visible)} lotes activos más."
        return reply, [
            {"label": "Ver subastas activas", "url": url_for("auction.active_auctions")}
        ] + [_auction_link(item) for item in visible]

    if any(term in normalized_question for term in ("direccion", "donde queda", "donde estan", "retirar", "retiro", "local", "envio", "envios", "costo de envio")):
        return (
            f"Podés retirar tus compras en {ADDRESS}. Para envíos, el costo depende de la ubicación; contactanos al {PHONE} o a {EMAIL} para coordinar.",
            [
                {"label": "Llamar", "url": "tel:+59896164645"},
                {"label": "WhatsApp", "url": "https://wa.me/59896164645"},
            ],
        )

    if any(term in normalized_question for term in ("telefono", "llamar", "contactar", "contacto", "mail", "correo", "email", "escribir")):
        return (
            f"Podés comunicarte por teléfono o WhatsApp al {PHONE}, o escribir a {EMAIL}.",
            [
                {"label": "Llamar", "url": "tel:+59896164645"},
                {"label": "WhatsApp", "url": "https://wa.me/59896164645"},
                {"label": "Enviar correo", "url": f"mailto:{EMAIL}"},
            ],
        )

    if any(term in normalized_question for term in ("comision", "porcentaje", "ganancia del remate", "recargo")):
        return (
            "A la oferta ganadora se le suma la comisión indicada en la ficha del lote. "
            "La comisión general es 20%; verificá siempre el porcentaje publicado para cada artículo.",
            [{"label": "Ver subastas activas", "url": url_for("auction.active_auctions")}],
        )

    if any(term in normalized_question for term in ("comprar", "compro", "pujar", "ofertar", "participar", "como funciona", "como hago")):
        return (
            "Para participar, creá una cuenta e iniciá sesión. Elegí un lote, leé su descripción y comprobá si la oferta es por el lote completo o por unidad. "
            "Ofertá antes del cierre; gana la oferta más alta. Al importe se suma la comisión indicada en la ficha. "
            "Si ganás, desde Mi cuenta podés registrar el método de pago y coordinar el retiro o envío.",
            [
                {"label": "Crear cuenta", "url": url_for("auth.register")},
                {"label": "Ver subastas", "url": url_for("auction.active_auctions")},
            ],
        )

    if any(term in normalized_question for term in ("plazo", "fecha", "horario", "cierra", "cierre", "cuenta atras", "cuanto tiempo")):
        return (
            "Cada lote tiene su propia fecha y hora de inicio y cierre, indicadas en su ficha en hora de Uruguay. "
            "La subasta acepta ofertas desde el inicio hasta que termina la cuenta regresiva; después del cierre no se puede ofertar.",
            [{"label": "Consultar subastas", "url": url_for("auction.active_auctions")}],
        )

    if any(term in normalized_question for term in ("recordatorio", "notificacion", "avisame", "aviso por correo")):
        return (
            "Si tenés una cuenta y empezaste sesión, podés activar en la ficha de una subasta próxima el aviso por correo. "
            "Te enviaremos un recordatorio 24 horas antes del inicio; si te suscribís más tarde, el próximo ciclo de avisos lo enviará.",
            [
                {
                    "label": "Ver próximas subastas",
                    "url": url_for("auction.upcoming_auctions"),
                }
            ],
        )

    if any(
        term in normalized_question
        for term in (
            "pago",
            "pagar",
            "tarjeta",
            "transferencia",
            "mercadopago",
            "brou",
            "redpagos",
            "mi dinero",
        )
    ):
        return (
            "Si ganás un lote, desde Mi cuenta podés registrar una transferencia al BROU "
            "(cuenta Nº 001901236, JUAN MARTINEZ) o a Mi Dinero Red Pagos "
            "(cuenta Nº 9102129). El pago queda pendiente hasta confirmar su recepción.",
            [
                {"label": "Ingresar", "url": url_for("auth.login")},
                {"label": "Contactar por correo", "url": f"mailto:{EMAIL}"},
            ],
        )

    return (
        "Puedo ayudarte con subastas activas o próximas, números de lote, horarios, comisión, formas de participar, pagos, dirección y contacto. "
        "Probá con una pregunta más concreta o escribinos al correo.",
        [{"label": "Enviar correo", "url": f"mailto:{EMAIL}"}],
    )


@help_bp.post("")
def answer_help_question():
    if request.content_length and request.content_length > 2048:
        return jsonify(error="La solicitud supera el tamaño permitido."), 413
    if not request.is_json:
        return jsonify(error="Enviá la pregunta como JSON."), 400
    payload = request.get_json(silent=True)
    question = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(question, str) or not question.strip():
        return jsonify(error="Escribí una pregunta para poder ayudarte."), 400
    question = question.strip()
    if len(question) > MAX_QUESTION_LENGTH:
        return jsonify(error=f"La pregunta no puede superar {MAX_QUESTION_LENGTH} caracteres."), 400

    reply, links = _answer(question)
    return jsonify(reply=reply, links=links)
