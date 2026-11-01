from functools import wraps
import hmac
import secrets

from flask import abort, request, session


def generate_csrf_token() -> str:
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_protect(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return view(*args, **kwargs)
        expected = session.get("csrf_token", "")
        provided = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, provided):
            abort(400, description="Token de seguridad inválido. Recargá la página.")
        return view(*args, **kwargs)

    return wrapped
