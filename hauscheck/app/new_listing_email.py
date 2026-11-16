from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.headerregistry import Address
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

import app.gmail_exchange as gmail_exchange
import app.immoscout_support as listing_sources
import app.main as main
import app.search_automation as search_automation
import app.search_performance as performance
from app.storage import connect, get_search_profile, list_search_candidates, now_iso, source_url_exists

# Nur erstmals gefundene passende bzw. prüfenswerte Inserate.
# Alte Kandidaten, Preisänderungen und erneut aktivierte Angebote lösen
# keine neue E-Mail aus. Analyse-Export und neue-Inserate-Mail bleiben getrennt.
_ELIGIBLE_STATUSES = {"new", "review"}
_BATCH_LIMIT = 10
_RETRY_DELAY_MINUTES = 15
_MAX_IMAGE_BYTES = 3 * 1024 * 1024
_PATCHED = False
_RUN_SEARCH: Callable[[str, int], Awaitable[int]] | None = None
_SEND_LOCK = asyncio.Lock()


def notifications_enabled() -> bool:
    value = search_automation._option("new_listing_email_enabled", False)
    return search_automation._truthy(value, False)


def ensure_notification_schema() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS new_listing_notifications (
                listing_key TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                sent_at TEXT,
                last_attempt_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_new_listing_mail_pending "
            "ON new_listing_notifications(sent_at, last_attempt_at)"
        )
        con.commit()


def _listing_key(url: str) -> str:
    provider = listing_sources.provider_for_url(url)
    external_id = listing_sources.external_id_for_url(url)
    if external_id:
        return f"{provider}:{external_id}".lower()
    return listing_sources.canonical_listing_url(url).strip().lower()


def _valid_listing_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError:
        return False


def _cached_images(url: str) -> list[str]:
    # Die Detailseite wurde bei der Suche bereits geparst. Keine zusätzliche
    # Portalabfrage nur für die Benachrichtigung starten.
    key = _listing_key(url)
    for parsed in reversed(list(performance._PARSE_CACHE.values())):
        if _listing_key(str(getattr(parsed, "source_url", "") or "")) == key:
            return [str(item) for item in (getattr(parsed, "image_urls", None) or [])]
    return []


def _enqueue_new_candidates(profile_id: str, previously_known_ids: set[str]) -> int:
    profile = get_search_profile(profile_id)
    if not profile:
        return 0
    added = 0
    with connect() as con:
        for candidate in list_search_candidates(profile_id):
            if str(candidate.get("id") or "") in previously_known_ids:
                continue
            status = str(candidate.get("status") or "")
            url = str(candidate.get("source_url") or "").strip()
            if status not in _ELIGIBLE_STATUSES or not _valid_listing_url(url):
                continue
            # Bereits bekannten Hausakten zugeordnete Fremdinserate sind keine
            # neuen Angebote und sollen keine Doppelmeldung erzeugen.
            if candidate.get("imported_house_id") or source_url_exists(url):
                continue
            images: list[str] = []
            for image_url in [str(candidate.get("preview_image_url") or ""), *_cached_images(url)]:
                if image_url and image_url not in images:
                    images.append(image_url)
                if len(images) == 2:
                    break
            payload = {
                "title": str(candidate.get("title") or "Neues Immobilienangebot"),
                "url": url,
                "profile": str(profile.get("name") or "Immobiliensuche"),
                "price_eur": candidate.get("price_eur"),
                "living_area_m2": candidate.get("living_area_m2"),
                "plot_area_m2": candidate.get("plot_area_m2"),
                "status": status,
                "image_urls": images,
            }
            cursor = con.execute(
                """
                INSERT OR IGNORE INTO new_listing_notifications
                    (listing_key, profile_id, source_url, payload_json, discovered_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_listing_key(url), profile_id, url, json.dumps(payload, ensure_ascii=False), now_iso()),
            )
            added += max(0, cursor.rowcount)
        con.commit()
    return added


def _safe_image_url(raw: str) -> str | None:
    url = str(raw or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not host
            or "." not in host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or host.endswith((".local", ".internal"))
        ):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            return url
    except ValueError:
        return None


def _jpeg_preview(raw: bytes) -> bytes:
    with Image.open(BytesIO(raw)) as source:
        if source.width * source.height > 24_000_000:
            raise ValueError("Bildauflösung zu groß")
        image = ImageOps.exif_transpose(source)
        image.thumbnail((1000, 800))
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
        return buffer.getvalue()


async def _prepare_images(urls: list[str]) -> list[tuple[str, bytes]]:
    previews: list[tuple[str, bytes]] = []
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        for image_url in urls[:2]:
            safe = _safe_image_url(image_url)
            if not safe:
                continue
            try:
                async with client.stream(
                    "GET",
                    safe,
                    headers={"User-Agent": "Mozilla/5.0 (HausCheck Pro)", "Accept": "image/avif,image/webp,image/jpeg,image/png,image/*"},
                ) as response:
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").lower().startswith("image/"):
                        continue
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > _MAX_IMAGE_BYTES:
                            raise ValueError("Vorschaubild zu groß")
                jpeg = await asyncio.to_thread(_jpeg_preview, bytes(content))
                previews.append((f"hauscheck_vorschau_{len(previews) + 1}.jpg", jpeg))
            except (httpx.HTTPError, ValueError, OSError) as exc:
                print(f"HausCheck Inserat-Mail: Vorschaubild nicht abrufbar: {exc}", flush=True)
    return previews


def _pretty_number(value: Any, unit: str = "") -> str:
    try:
        number = float(value)
        result = f"{int(number):,}".replace(",", ".") if number.is_integer() else f"{number:g}"
        return result + unit
    except (TypeError, ValueError, OverflowError):
        return "nicht angegeben"


def _build_notification_mail(
    settings: gmail_exchange.GmailExchangeSettings,
    data: dict[str, Any],
    images: list[tuple[str, bytes]],
) -> EmailMessage:
    title = str(data.get("title") or "Neues Immobilienangebot").strip()[:130]
    url = str(data["url"])
    price = _pretty_number(data.get("price_eur"), " €")
    living = _pretty_number(data.get("living_area_m2"), " m²")
    plot = _pretty_number(data.get("plot_area_m2"), " m²")
    profile = str(data.get("profile") or "Immobiliensuche")
    status = "Zur Prüfung" if data.get("status") == "review" else "Passend"

    msg = EmailMessage()
    msg["Subject"] = f"Neues Inserat: {title[:85]}"
    msg["From"] = Address(display_name=settings.from_name or "HausCheck Pro", addr_spec=settings.username)
    msg["To"] = settings.to
    msg.set_content(
        f"Neues Immobilieninserat über HausCheck Pro\n\n"
        f"{title}\nSuchprofil: {profile}\nEinstufung: {status}\n"
        f"Preis: {price}\nWohnfläche: {living}\nGrundstück: {plot}\n\n"
        f"Direkt zum Inserat:\n{url}\n\n"
        "Diese Nachricht ist ein neuer Suchtreffer, kein KI-Analyseauftrag."
    )

    image_markup = "".join(
        f'<div style="margin-top:14px"><img src="cid:hauscheck-neu-{index}@local" '
        f'alt="Inseratfoto {index}" style="display:block;max-width:100%;height:auto;border-radius:10px"></div>'
        for index in range(1, len(images) + 1)
    )
    safe_url = html.escape(url, quote=True)
    msg.add_alternative(
        '<html><body style="font-family:Arial,sans-serif;line-height:1.55;color:#253045">'
        '<div style="max-width:600px;margin:auto">'
        '<p style="color:#64748b">HausCheck Pro · neues Immobilienangebot</p>'
        f'<h2>{html.escape(title)}</h2>'
        f'<p><b>Suchprofil:</b> {html.escape(profile)}<br>'
        f'<b>Einstufung:</b> {status}<br>'
        f'<b>Preis:</b> {html.escape(price)}<br>'
        f'<b>Wohnfläche:</b> {html.escape(living)}<br>'
        f'<b>Grundstück:</b> {html.escape(plot)}</p>'
        f'<p><a href="{safe_url}" style="font-weight:bold">Inserat direkt öffnen</a></p>'
        f'{image_markup}'
        '<p style="color:#64748b;font-size:12px">Benachrichtigung über ein erstmals gefundenes Inserat.'
        ' Kein KI-Analyseauftrag.</p></div></body></html>',
        subtype="html",
    )
    html_part = msg.get_payload()[-1]
    for index, (filename, image) in enumerate(images, start=1):
        html_part.add_related(
            image,
            maintype="image",
            subtype="jpeg",
            cid=f"<hauscheck-neu-{index}@local>",
            filename=filename,
            disposition="inline",
        )
    return msg


def _send_smtp_sync(settings: gmail_exchange.GmailExchangeSettings, msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=45) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.username, settings.app_password)
        smtp.send_message(msg)


async def send_pending_notifications() -> int:
    if not notifications_enabled():
        return 0
    settings = gmail_exchange.load_gmail_settings()
    # Die neue Inserat-Mail nutzt dieselbe bestehende SMTP-Konfiguration.
    # gmail_auto_send_on_import steuert ausschließlich den alten Exportweg.
    if not settings.send_ready:
        print("HausCheck Inserat-Mail: SMTP nicht eingerichtet oder Gmail deaktiviert", flush=True)
        return 0
    async with _SEND_LOCK:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=_RETRY_DELAY_MINUTES)).isoformat()
        with connect() as con:
            rows = con.execute(
                """
                SELECT listing_key, payload_json FROM new_listing_notifications
                WHERE sent_at IS NULL
                  AND (last_attempt_at IS NULL OR last_attempt_at <= ?)
                ORDER BY discovered_at ASC
                LIMIT ?
                """,
                (cutoff, _BATCH_LIMIT),
            ).fetchall()
        delivered = 0
        for row in rows:
            key = str(row["listing_key"])
            try:
                payload = json.loads(row["payload_json"])
                images = await _prepare_images(payload.get("image_urls") or [])
                msg = _build_notification_mail(settings, payload, images)
                await asyncio.to_thread(_send_smtp_sync, settings, msg)
                with connect() as con:
                    con.execute(
                        """
                        UPDATE new_listing_notifications
                        SET sent_at = ?, last_attempt_at = ?, attempts = attempts + 1, last_error = NULL
                        WHERE listing_key = ? AND sent_at IS NULL
                        """,
                        (now_iso(), now_iso(), key),
                    )
                    con.commit()
                delivered += 1
                print(f"HausCheck Inserat-Mail versendet: {key} ({len(images)} Bilder)", flush=True)
            except Exception as exc:
                with connect() as con:
                    con.execute(
                        """
                        UPDATE new_listing_notifications
                        SET last_attempt_at = ?, attempts = attempts + 1, last_error = ?
                        WHERE listing_key = ? AND sent_at IS NULL
                        """,
                        (now_iso(), str(exc)[:500], key),
                    )
                    con.commit()
                print(f"HausCheck Inserat-Mail fehlgeschlagen: {key}: {exc}", flush=True)
        return delivered


async def run_search_with_new_listing_email(profile_id: str, max_results: int = 80) -> int:
    if _RUN_SEARCH is None:
        raise RuntimeError("Suchroutine ist noch nicht registriert")
    before_ids = {str(item.get("id") or "") for item in list_search_candidates(profile_id)}
    found = await _RUN_SEARCH(profile_id, max_results)
    try:
        if notifications_enabled():
            added = _enqueue_new_candidates(profile_id, before_ids)
            sent = await send_pending_notifications()
            if added or sent:
                print(f"HausCheck neue Inserate: vorgemerkt={added}, versendet={sent}", flush=True)
    except Exception as exc:
        # Ein E-Mail-Problem darf die erfolgreiche Immobiliensuche nicht zurückrollen.
        print(f"HausCheck Inserat-Benachrichtigungen: {exc}", flush=True)
    return found


def register_new_listing_email() -> None:
    global _PATCHED, _RUN_SEARCH
    if _PATCHED:
        return
    ensure_notification_schema()
    # Als letzter Wrapper nach dem finalen Suchrunner: trifft automatische
    # Profilzyklen und den manuellen Suchknopf in allen Portaladaptern.
    _RUN_SEARCH = search_automation.run_search_profile
    search_automation.run_search_profile = run_search_with_new_listing_email
    main.run_search_profile = run_search_with_new_listing_email
    _PATCHED = True
