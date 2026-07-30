from __future__ import annotations

import imaplib
import inspect
import socket
import ssl
from typing import Any, Callable
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import RedirectResponse


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _take_route(app: FastAPI, path: str, method: str) -> Callable[..., Any] | None:
    for route in list(app.router.routes):
        if getattr(route, "path", "") == path and method in _methods(route):
            app.router.routes.remove(route)
            return getattr(route, "endpoint", None)
    return None


async def _call(endpoint: Callable[..., Any]) -> Any:
    result = endpoint()
    return await result if inspect.isawaitable(result) else result


def _error_text(exc: BaseException) -> str:
    text = str(exc).strip()
    if text.startswith("b'") and text.endswith("'"):
        text = text[2:-1]
    return " ".join(text.replace("\\r", " ").replace("\\n", " ").split())


def friendly_mail_error(exc: BaseException) -> str:
    text = _error_text(exc)
    upper = text.upper()

    if isinstance(exc, imaplib.IMAP4.error) and (
        "AUTHENTICATIONFAILED" in upper
        or "INVALID CREDENTIAL" in upper
        or "LOGIN FAILED" in upper
        or "AUTHENTICATION FAILED" in upper
    ):
        return (
            "Anmeldung beim Postfach fehlgeschlagen. Bei Gmail muss in HausCheck ein "
            "16-stelliges Google-App-Passwort eingetragen werden, nicht das normale "
            "Google-Passwort. Benutzername ist die vollständige Gmail-Adresse."
        )

    if isinstance(exc, imaplib.IMAP4.error):
        return f"Der IMAP-Server hat die Anmeldung oder Anfrage abgelehnt: {text[:300]}"

    if isinstance(exc, socket.gaierror):
        return "Der IMAP-Servername konnte nicht gefunden werden. Bitte IMAP-Host prüfen."

    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Zeitüberschreitung beim IMAP-Server. Host, Port und Internetverbindung prüfen."

    if isinstance(exc, ssl.SSLError):
        return "Die verschlüsselte Verbindung zum IMAP-Server ist fehlgeschlagen. TLS-Port prüfen."

    if isinstance(exc, ConnectionRefusedError):
        return "Der IMAP-Server hat die Verbindung abgelehnt. Host und Port prüfen."

    if isinstance(exc, OSError):
        return f"Verbindung zum IMAP-Server fehlgeschlagen: {text[:300]}"

    if "ORDNER KONNTE NICHT GEÖFFNET" in upper or "MAILBOX" in upper:
        return f"Der konfigurierte IMAP-Ordner konnte nicht geöffnet werden: {text[:300]}"

    return f"Postfachprüfung fehlgeschlagen: {text[:300] or type(exc).__name__}"


def register_mail_inbox_error_handling(app: FastAPI) -> None:
    if getattr(app.state, "mail_inbox_error_handling_registered", False):
        return

    endpoint = _take_route(app, "/mail-inbox/refresh", "POST")
    if endpoint is None:
        return

    @app.post("/mail-inbox/refresh")
    async def refresh_mail_inbox_safe() -> RedirectResponse:
        try:
            return await _call(endpoint)
        except Exception as exc:
            print(
                f"HausCheck E-Mail-Posteingang Abruf fehlgeschlagen: "
                f"{type(exc).__name__}: {_error_text(exc)[:500]}",
                flush=True,
            )
            message = friendly_mail_error(exc)
            return RedirectResponse(
                f"../mail-inbox?message={quote(message)}",
                status_code=303,
            )

    app.state.mail_inbox_error_handling_registered = True
