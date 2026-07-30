from __future__ import annotations

from typing import Callable

import app.modern_ui as modern_ui
from app.mail_import_android_fix import register_mail_import_android_fix
from app.mail_inbox import register_mail_inbox
from app.mail_inbox_error_handling import register_mail_inbox_error_handling
from app.mail_inbox_route_fix import register_mail_inbox_route_fix
from app.main import app
from app.storage import list_media, list_sources
from app.supervisor_update_refresh import register_supervisor_update_refresh
from app.ui_helpers import esc


MAIL_SOURCE_SCHEMES = ("mail-import://", "mail-inbox://")


def register_mail_import_source_ui() -> None:
    # Wird direkt nach register_mail_import(app) aufgerufen und ersetzt dessen
    # Android-inkompatiblen Dateifilter durch eine sichere Inhaltsprüfung.
    register_mail_import_android_fix(app)
    # Der Posteingang wird bewusst erst nach dem manuellen Import registriert,
    # damit er dessen finale Importseite ergänzt statt eine Parallel-UI zu bauen.
    register_mail_inbox(app)
    # Relative Formular- und Kartenpfade werden an den tatsächlichen Ingress-Pfad
    # gebunden, damit sie mit und ohne abschließenden Schrägstrich funktionieren.
    register_mail_inbox_route_fix(app)
    # Erwartbare IMAP-, Login- und Netzwerkfehler werden im Posteingang verständlich
    # angezeigt und erzeugen keinen unbrauchbaren HTTP-500-Fehler mehr.
    register_mail_inbox_error_handling(app)
    # Letzte UI-Erweiterung: Home-Assistant-App-Store bei Bedarf direkt neu laden.
    register_supervisor_update_refresh(app)

    current: Callable[[str], str] = modern_ui._sources_html
    if getattr(current, "_mail_import_source_ui_patched", False):
        return

    def sources_with_mail_import(house_id: str) -> str:
        sources = list_sources(house_id)
        if not any(str(source.get("source_url") or "").startswith(MAIL_SOURCE_SCHEMES) for source in sources):
            return current(house_id)
        if not sources:
            return '<p class="muted">Keine Quelle gespeichert.</p>'

        media = list_media(house_id)
        cards: list[str] = []
        for index, source in enumerate(reversed(sources), start=1):
            source_id = str(source.get("id") or "")
            url = str(source.get("source_url") or "")
            if url.startswith(MAIL_SOURCE_SCHEMES):
                originals = [
                    item
                    for item in media
                    if str(item.get("source_id") or "") == source_id
                    and item.get("kind") == "email"
                    and item.get("download_status") == "downloaded"
                ]
                original_links = "".join(
                    f'<a class="button ghost" href="../media/{esc(item.get("id"))}" target="_blank">{modern_ui.icon("external")} Original-E-Mail öffnen</a>'
                    for item in originals
                )
                source_kind = "Posteingang" if url.startswith("mail-inbox://") else "Manueller Import"
                cards.append(
                    f"""
                    <div class="source-card">
                      <strong>E-Mail-/Dokumentquelle {index}: {esc(source.get('source_name') or source_kind)}</strong>
                      <p class="muted">{esc(source.get('description') or 'Original-E-Mail, Anhänge und Feldherkunft wurden lokal archiviert.')}</p>
                      <p class="muted">{esc(source_kind)} · Importstatus {esc(source.get('parser_status') or 'partial')} · {esc(modern_ui.format_datetime(source.get('updated_at')))}</p>
                      {original_links or '<span class="pill">Original in der Hausakte archiviert</span>'}
                    </div>
                    """
                )
            else:
                cards.append(
                    f"""
                    <div class="source-card">
                      <strong>Inserat {index}: {esc(source.get('source_name') or 'Quelle')}</strong>
                      <p class="muted">ID {esc(source.get('external_id') or '–')} · zuletzt gelesen {esc(modern_ui.format_datetime(source.get('updated_at')))}</p>
                      <a class="button ghost" href="{esc(url)}" target="_blank">{modern_ui.icon('external')} Inserat öffnen</a>
                    </div>
                    """
                )
        return '<div class="grid">' + "".join(cards) + "</div>"

    setattr(sources_with_mail_import, "_mail_import_source_ui_patched", True)
    modern_ui._sources_html = sources_with_mail_import
