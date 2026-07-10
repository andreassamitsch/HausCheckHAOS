from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse

from app.parser import parse_listing
from app.storage import (
    PROJECTS_DIR,
    add_evidence,
    add_media,
    create_house,
    create_source,
    get_house,
    get_media,
    init_storage,
    list_evidence,
    list_houses,
    list_media,
    list_sources,
    project_dir,
    update_media,
)

APP_NAME = "HausCheck Pro"
USER_AGENT = "Mozilla/5.0 (HausCheckHAOS; private research tool) AppleWebKit/537.36"

app = FastAPI(title=APP_NAME, version="0.1.1")


@app.on_event("startup")
def startup() -> None:
    init_storage()


def esc(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def money(value: object) -> str:
    if value in (None, ""):
        return "–"
    try:
        return f"{int(float(value)):,.0f} €".replace(",", ".")
    except Exception:
        return esc(value)


def num(value: object, suffix: str = "") -> str:
    if value in (None, ""):
        return "–"
    try:
        number = float(value)
        if number.is_integer():
            return f"{int(number)}{suffix}"
        return f"{number:.1f}{suffix}".replace(".", ",")
    except Exception:
        return f"{esc(value)}{suffix}"


def layout(title: str, body: str, home_href: str = "./") -> HTMLResponse:
    """Render page with relative links so it works through Home Assistant Ingress."""
    return HTMLResponse(
        f"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    body {{ margin: 0; background: #101418; color: #eef2f4; }}
    header {{ position: sticky; top: 0; z-index: 2; padding: 14px 16px; background: #17212b; border-bottom: 1px solid #26323e; }}
    header a {{ color: #eef2f4; text-decoration: none; font-weight: 700; }}
    main {{ padding: 16px; max-width: 1100px; margin: 0 auto; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .card {{ background: #17212b; border: 1px solid #26323e; border-radius: 14px; padding: 14px; box-shadow: 0 2px 10px rgba(0,0,0,.18); }}
    .card h2, .card h3 {{ margin-top: 0; }}
    .muted {{ color: #aab4bd; }}
    .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #243342; margin: 2px 4px 2px 0; font-size: 12px; }}
    .warn {{ color: #ffd27a; }}
    .danger {{ color: #ff9c9c; }}
    a {{ color: #8fd3ff; }}
    input, textarea, select {{ width: 100%; box-sizing: border-box; padding: 10px; margin: 6px 0 12px; border-radius: 10px; border: 1px solid #3a4856; background: #0f151b; color: #eef2f4; }}
    button, .button {{ display: inline-block; padding: 10px 14px; border-radius: 10px; border: 0; background: #2f80ed; color: white; text-decoration: none; font-weight: 700; cursor: pointer; }}
    .button.secondary, button.secondary {{ background: #394957; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 8px; border-bottom: 1px solid #26323e; text-align: left; vertical-align: top; }}
    img.thumb {{ width: 100%; max-height: 180px; object-fit: cover; border-radius: 10px; background: #0b0f13; }}
    .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }}
    pre {{ white-space: pre-wrap; background: #0f151b; padding: 12px; border-radius: 10px; overflow-wrap: anywhere; }}
  </style>
</head>
<body>
<header><a href="{esc(home_href)}">🏠 HausCheck Pro</a></header>
<main>{body}</main>
</body>
</html>
"""
    )


def first_local_image(house_id: str, prefix: str = "") -> str | None:
    for media in list_media(house_id):
        if media.get("kind") == "image" and media.get("download_status") == "downloaded" and media.get("local_path"):
            return f"{prefix}media/{media['id']}"
    return None


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    houses = list_houses()
    cards = []
    for house in houses:
        img = first_local_image(house["id"])
        image_html = f'<img class="thumb" src="{img}" alt="Bild">' if img else '<div class="muted">Noch kein lokales Bild</div>'
        cards.append(
            f"""
            <div class="card">
              {image_html}
              <h3>{esc(house.get('title'))}</h3>
              <div class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</div>
              <p>
                <span class="pill">{money(house.get('price_eur'))}</span>
                <span class="pill">{num(house.get('living_area_m2'), ' m² Wfl.')}</span>
                <span class="pill">{num(house.get('plot_area_m2'), ' m² Grund')}</span>
              </p>
              <p><span class="pill">Status: {esc(house.get('status'))}</span><span class="pill">Adresse: {esc(house.get('address_status'))}</span></p>
              <a class="button" href="houses/{house['id']}">Hausakte öffnen</a>
            </div>
            """
        )
    body = f"""
    <div class="grid">
      <div class="card">
        <h2>Neue Hausakte</h2>
        <p class="muted">Direktlink importieren oder Objekt manuell anlegen.</p>
        <a class="button" href="import">Inserat importieren</a>
      </div>
      <div class="card">
        <h2>Status</h2>
        <p><span class="pill">{len(houses)} Hausakten</span></p>
        <p class="muted">v0.1.1 Fundament: HA Ingress, SQLite, Hausakte, Direktlink-Import.</p>
      </div>
    </div>
    <h2>Hausakten</h2>
    <div class="grid">{''.join(cards) if cards else '<div class="card muted">Noch keine Objekte vorhanden.</div>'}</div>
    """
    return layout("HausCheck", body, home_href="./")


@app.get("/import", response_class=HTMLResponse)
def import_form() -> HTMLResponse:
    body = """
    <div class="card">
      <h2>Inserat importieren</h2>
      <form method="post" action="import">
        <label>Direktlink</label>
        <input name="url" placeholder="https://www.willhaben.at/iad/immobilien/d/..." required>
        <button type="submit">Importieren</button>
      </form>
      <p class="muted">Aktuell: erster Direktlink-Import mit Willhaben-Parser und generischem Fallback.</p>
    </div>
    <div class="card">
      <h2>Manuell anlegen</h2>
      <form method="post" action="manual">
        <label>Titel</label><input name="title" required>
        <label>Ort/Lage</label><input name="location_text">
        <label>Preis €</label><input name="price_eur" type="number">
        <label>Wohnfläche m²</label><input name="living_area_m2" type="number" step="0.1">
        <label>Grundstück m²</label><input name="plot_area_m2" type="number" step="0.1">
        <button type="submit">Hausakte anlegen</button>
      </form>
    </div>
    """
    return layout("Inserat importieren", body, home_href="../")


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


@app.post("/import")
async def import_url(url: str = Form(...)) -> RedirectResponse:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Ungültige URL")
    raw_html = await fetch_html(url)
    parsed = parse_listing(url, raw_html)

    house = create_house(
        {
            "title": parsed.title,
            "location_text": parsed.location_text,
            "address_status": parsed.address_status,
            "price_eur": parsed.price_eur,
            "living_area_m2": parsed.living_area_m2,
            "plot_area_m2": parsed.plot_area_m2,
            "rooms": parsed.rooms,
            "year_built": parsed.year_built,
            "heating": parsed.heating,
            "energy_hwb": parsed.energy_hwb,
            "energy_fgee": parsed.energy_fgee,
            "energy_class_hwb": parsed.energy_class_hwb,
            "energy_class_fgee": parsed.energy_class_fgee,
        }
    )
    hdir = project_dir(house["id"])
    html_path = hdir / "html" / "listing.html"
    html_path.write_text(raw_html, encoding="utf-8")

    source = create_source(
        house["id"],
        {
            "source_name": parsed.source_name,
            "source_url": parsed.source_url,
            "external_id": parsed.external_id,
            "description": parsed.description,
            "raw_html_path": str(html_path),
            "parser_status": "success" if not parsed.warnings else "partial",
            "parser_warnings": parsed.warnings,
        },
    )
    add_evidence(house["id"], source["id"], parsed.evidence)

    for image_url in parsed.image_urls:
        add_media(house["id"], {"source_id": source["id"], "kind": "image", "original_url": image_url, "download_status": "pending"})
    for pdf_url in parsed.pdf_urls:
        add_media(house["id"], {"source_id": source["id"], "kind": "pdf", "original_url": pdf_url, "download_status": "pending"})

    return RedirectResponse(f"houses/{house['id']}", status_code=303)


@app.post("/manual")
def manual_create(
    title: str = Form(...),
    location_text: str | None = Form(None),
    price_eur: int | None = Form(None),
    living_area_m2: float | None = Form(None),
    plot_area_m2: float | None = Form(None),
) -> RedirectResponse:
    house = create_house(
        {
            "title": title,
            "location_text": location_text,
            "price_eur": price_eur,
            "living_area_m2": living_area_m2,
            "plot_area_m2": plot_area_m2,
            "address_status": "unknown",
        }
    )
    return RedirectResponse(f"houses/{house['id']}", status_code=303)


@app.get("/houses/{house_id}", response_class=HTMLResponse)
def house_detail(house_id: str) -> HTMLResponse:
    house = get_house(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
    sources = list_sources(house_id)
    media = list_media(house_id)
    evidence = list_evidence(house_id)

    source_rows = "".join(
        f"<tr><td>{esc(src.get('source_name'))}</td><td><a href='{esc(src.get('source_url'))}' target='_blank'>Direktlink</a></td><td>{esc(src.get('parser_status'))}</td></tr>"
        for src in sources
    )
    media_items = []
    for item in media:
        if item.get("kind") == "image" and item.get("download_status") == "downloaded":
            media_items.append(f"<a href='../media/{item['id']}' target='_blank'><img class='thumb' src='../media/{item['id']}' alt='Bild'></a>")
    media_html = "".join(media_items) if media_items else "<p class='muted'>Noch keine heruntergeladenen Bilder.</p>"
    pending_count = len([m for m in media if m.get("download_status") == "pending"])
    failed_count = len([m for m in media if m.get("download_status") == "failed"])

    evidence_rows = "".join(
        f"<tr><td>{esc(ev.get('field_name'))}</td><td>{esc(ev.get('value_text'))}</td><td>{esc(ev.get('confidence'))}</td><td>{esc(ev.get('source_text_snippet'))}</td></tr>"
        for ev in evidence[:30]
    )

    failed_rows = "".join(
        f"<tr><td>{esc(m.get('kind'))}</td><td>{esc(m.get('original_url'))}</td><td class='danger'>{esc(m.get('download_error'))}</td></tr>"
        for m in media
        if m.get("download_status") == "failed"
    )
    failed_html = f"<h3>Fehlgeschlagene Medien</h3><table><tr><th>Typ</th><th>URL</th><th>Fehler</th></tr>{failed_rows}</table>" if failed_rows else ""

    body = f"""
    <div class="card">
      <h2>{esc(house.get('title'))}</h2>
      <p class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</p>
      <p>
        <span class="pill">{money(house.get('price_eur'))}</span>
        <span class="pill">{num(house.get('living_area_m2'), ' m² Wfl.')}</span>
        <span class="pill">{num(house.get('plot_area_m2'), ' m² Grund')}</span>
        <span class="pill">HWB {num(house.get('energy_hwb'))}</span>
        <span class="pill">fGEE {num(house.get('energy_fgee'))}</span>
        <span class="pill">Heizung: {esc(house.get('heating') or 'unbekannt')}</span>
      </p>
      <p><span class="pill">Adresse: {esc(house.get('address_status'))}</span><span class="pill">Status: {esc(house.get('status'))}</span></p>
      <form method="post" action="{house_id}/download-media" style="display:inline">
        <button type="submit">Medien herunterladen ({pending_count} offen, {failed_count} Fehler)</button>
      </form>
      <a class="button secondary" href="{house_id}/briefing">Analysebriefing</a>
    </div>

    <div class="card">
      <h2>Bilder</h2>
      <div class="gallery">{media_html}</div>
      <h3>Manuell hochladen</h3>
      <form method="post" action="{house_id}/upload" enctype="multipart/form-data">
        <input type="file" name="file" required>
        <button type="submit">Hochladen</button>
      </form>
      {failed_html}
    </div>

    <div class="card">
      <h2>Quellen</h2>
      <table><tr><th>Portal</th><th>Link</th><th>Status</th></tr>{source_rows}</table>
    </div>

    <div class="card">
      <h2>Feldherkunft</h2>
      <table><tr><th>Feld</th><th>Wert</th><th>Sicherheit</th><th>Snippet</th></tr>{evidence_rows}</table>
    </div>
    """
    return layout(str(house.get("title") or "Hausakte"), body, home_href="../")


def safe_filename_from_url(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or fallback
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    if "." not in name:
        name = f"{name}.jpg"
    return name[:180]


@app.post("/houses/{house_id}/download-media")
async def download_media(house_id: str) -> RedirectResponse:
    house = get_house(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
    hdir = project_dir(house_id)
    media = [m for m in list_media(house_id) if m.get("download_status") == "pending" and m.get("original_url")]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for item in media[:80]:
            try:
                url = item["original_url"]
                response = await client.get(url)
                response.raise_for_status()
                kind_dir = "pdfs" if item.get("kind") == "pdf" else "images"
                filename = safe_filename_from_url(url, f"{item['id']}.bin")
                target = hdir / kind_dir / filename
                target.write_bytes(response.content)
                update_media(
                    item["id"],
                    {
                        "local_path": str(target),
                        "mime_type": response.headers.get("content-type"),
                        "download_status": "downloaded",
                        "download_error": None,
                    },
                )
            except Exception as exc:
                update_media(item["id"], {"download_status": "failed", "download_error": str(exc)[:500]})
    return RedirectResponse(f"../{house_id}", status_code=303)


@app.post("/houses/{house_id}/upload")
async def upload_media(house_id: str, file: UploadFile = File(...)) -> RedirectResponse:
    if not get_house(house_id):
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "upload.bin")
    ext = Path(filename).suffix.lower()
    kind = "pdf" if ext == ".pdf" else "image"
    sub = "pdfs" if kind == "pdf" else "images"
    target = project_dir(house_id) / sub / filename
    target.write_bytes(await file.read())
    add_media(
        house_id,
        {
            "kind": kind,
            "local_path": str(target),
            "mime_type": file.content_type,
            "download_status": "downloaded",
        },
    )
    return RedirectResponse(f"../{house_id}", status_code=303)


@app.get("/media/{media_id}")
def media_file(media_id: str) -> FileResponse:
    item = get_media(media_id)
    if not item or not item.get("local_path"):
        raise HTTPException(status_code=404, detail="Medium nicht gefunden")
    path = Path(item["local_path"])
    try:
        path.relative_to(PROJECTS_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Ungültiger Medienpfad") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse(path)


@app.get("/houses/{house_id}/briefing")
def briefing(house_id: str) -> PlainTextResponse:
    house = get_house(house_id)
    if not house:
        raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
    sources = list_sources(house_id)
    media = list_media(house_id)
    evidence = list_evidence(house_id)
    source_links = "\n".join(f"- {s.get('source_name')}: {s.get('source_url')}" for s in sources)
    evidence_lines = "\n".join(
        f"- {e.get('field_name')}: {e.get('value_text')} ({e.get('confidence')}) – {e.get('source_text_snippet')}"
        for e in evidence[:50]
    )
    local_images = len([m for m in media if m.get("kind") == "image" and m.get("download_status") == "downloaded"])
    pending = len([m for m in media if m.get("download_status") == "pending"])
    text = f"""# Analysebriefing: {house.get('title')}

## Stammdaten

- Ort/Lage: {house.get('location_text') or 'unbekannt'}
- Adressstatus: {house.get('address_status')}
- Preis: {house.get('price_eur')}
- Wohnfläche: {house.get('living_area_m2')}
- Grundstück: {house.get('plot_area_m2')}
- Baujahr: {house.get('year_built')}
- Heizung: {house.get('heating')}
- HWB: {house.get('energy_hwb')}
- fGEE: {house.get('energy_fgee')}

## Quellen

{source_links or '- keine'}

## Medien

- Lokale Bilder: {local_images}
- Offene Downloads: {pending}

## Feldherkunft

{evidence_lines or '- keine Feldherkunft erfasst'}

## Hinweise

- Fehlende Werte wurden nicht erfunden.
- Grundstück darf nur verwendet werden, wenn es explizit erkannt wurde.
- Ohne genaue Adresse ist keine belastbare Lageprüfung möglich.
"""
    return PlainTextResponse(text)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME}
