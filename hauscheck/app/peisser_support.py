from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException

import app.candidate_preimport_dedupe as candidate_dedupe
import app.immoscout_dynamic_search as dynamic
import app.immoscout_support as support
import app.import_patch as import_patch
import app.main as main
import app.modern_ui as modern_ui
import app.parser as parser_module
import app.search_automation as search_automation
import app.search_lifecycle_ui as lifecycle_ui
import app.immoscout_url_runtime_fix as runtime_fix
from app.parser import ParsedListing
from app.pipeline_status import set_pipeline_stage
from app.storage import (
    add_evidence,
    connect,
    create_house,
    get_house,
    get_search_profile,
    list_media,
    list_search_candidates,
    mark_candidates_imported,
    now_iso,
    update_search_profile_run,
    upsert_search_candidate,
)


PEISSER_SOURCE = "peisser-immobilien.at"
PEISSER_HOST = "www.peisser-immobilien.at"
PEISSER_BASE = f"https://{PEISSER_HOST}/"
PEISSER_SEARCH_URL = f"{PEISSER_BASE}index.php?page=1&view=index&mode=entry&lang=de"
PEISSER_MAX_PAGES = 10
HOUSE_TYPES = {"haus", "einfamilienhaus", "mehrfamilienhaus", "wohnimmobilie"}
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}

_PATCHED = False
_ORIGINAL_PROVIDER: Callable[[str], str] | None = None
_ORIGINAL_EXTERNAL_ID: Callable[[str], str | None] | None = None
_ORIGINAL_CANONICAL: Callable[[str], str] | None = None
_ORIGINAL_PARSE: Callable[[str, str], ParsedListing] | None = None
_ORIGINAL_FETCH_HTML: Callable[[str], Awaitable[str]] | None = None
_ORIGINAL_RESOLVE_URLS: Callable[[dict[str, Any]], list[str]] | None = None
_ORIGINAL_VALIDATE: Callable[..., tuple[str, str]] | None = None
_ORIGINAL_FORM: Callable[..., str] | None = None
_ORIGINAL_PROFILE_CARD: Callable[[dict[str, Any]], str] | None = None
_ORIGINAL_RUN_SEARCH: Callable[[str, int], Awaitable[int]] | None = None
_ORIGINAL_IMPORT: Callable[..., Awaitable[dict[str, Any]]] | None = None
_ORIGINAL_REMOTE_HASHES: Callable[..., Awaitable[list[str]]] | None = None


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: object) -> str:
    text = _clean(value).lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_peisser_url(url: str) -> bool:
    host = urlsplit(str(url or "")).netloc.lower().split(":", 1)[0]
    return host in {PEISSER_HOST, "peisser-immobilien.at"}


def peisser_entry_id(url: str) -> str | None:
    if not is_peisser_url(url):
        return None
    parts = urlsplit(str(url or ""))
    if not parts.path.endswith("expose.php"):
        return None
    value = (parse_qs(parts.query).get("id") or [None])[0]
    return str(value) if value and re.fullmatch(r"[0-9]+", str(value)) else None


def provider_for_url_all(url: str) -> str:
    if is_peisser_url(url):
        return PEISSER_SOURCE
    return _ORIGINAL_PROVIDER(url) if _ORIGINAL_PROVIDER else support.WILLHABEN_SOURCE


def external_id_for_url_all(url: str) -> str | None:
    if is_peisser_url(url):
        return peisser_entry_id(url)
    return _ORIGINAL_EXTERNAL_ID(url) if _ORIGINAL_EXTERNAL_ID else None


def canonical_listing_url_all(url: str) -> str:
    if not is_peisser_url(url):
        return _ORIGINAL_CANONICAL(url) if _ORIGINAL_CANONICAL else str(url or "")
    entry_id = peisser_entry_id(url)
    if entry_id:
        return f"{PEISSER_BASE}expose.php?id={entry_id}"
    parts = urlsplit(str(url or ""))
    return urlunsplit(("https", PEISSER_HOST, parts.path or "/", urlencode(sorted(parse_qs(parts.query).items())), ""))


def title_from_url_all(url: str) -> str:
    if is_peisser_url(url):
        entry_id = peisser_entry_id(url)
        return f"Peisser Immobilien Exposé {entry_id}" if entry_id else "Peisser Immobilien Inserat"
    return support.title_from_listing_url_multi(url)


def _number(value: object) -> float | None:
    return support._number(value)


def _label_number(text: str, labels: tuple[str, ...], unit: str | None = None) -> tuple[float | None, str | None]:
    label = "|".join(re.escape(item) for item in labels)
    suffix = rf"\s*{unit}" if unit else ""
    match = re.search(rf"(?:{label})\s*:\s*(?:ca\.\s*)?([0-9][0-9\.\s]*(?:,[0-9]+)?){suffix}", text, re.I)
    if not match:
        return None, None
    return _number(match.group(1)), match.group(0)


def _add_evidence(result: ParsedListing, field: str, value: object, label: str, snippet: str | None, confidence: str = "verified") -> None:
    if value in (None, ""):
        return
    result.evidence.append(
        {
            "field_name": field,
            "value": value,
            "source_label": label,
            "source_text_snippet": str(snippet or "")[:300] or None,
            "confidence": confidence,
        }
    )


def _section(soup: BeautifulSoup, name: str) -> Any:
    return soup.select_one(f"section[data-peisser-view='{name}']") or soup


def _object_type(text: str) -> str | None:
    match = re.search(r"Objektart\s*:\s*([^|]{1,80}?)(?=\s+Vermarktung\s*:|\s+Anschrift\s*:|$)", text, re.I)
    return _clean(match.group(1)) if match else None


def _sold_title(title: object) -> bool:
    return bool(re.search(r"\bVERKAUFT\b", str(title or ""), re.I))


def parse_peisser(url: str, raw_html: str) -> ParsedListing:
    entry_id = peisser_entry_id(url)
    soup = BeautifulSoup(raw_html, "html.parser")
    detail = _section(soup, "details")
    texts = _section(soup, "texts")
    gallery = _section(soup, "gallery")
    detail_text = _clean(detail.get_text(" ", strip=True))
    texts_text = _clean(texts.get_text(" ", strip=True))
    all_text = f"{detail_text} {texts_text}"

    result = ParsedListing(source_name=PEISSER_SOURCE, source_url=canonical_listing_url_all(url), external_id=entry_id)

    object_match = re.search(r"Objekt-Nr\s*:\s*([A-Za-z0-9_-]+)", detail_text, re.I)
    object_number = object_match.group(1) if object_match else None
    if object_number:
        result.external_id = object_number
        _add_evidence(result, "external_id", object_number, "Peisser Objekt-Nr.", object_match.group(0))

    title_candidates = re.findall(r"Übersicht\s+(.{8,320}?)\s+Objekt-Nr\s*:", detail_text, re.I)
    title_candidates = [_clean(item) for item in title_candidates if _clean(item)]
    if title_candidates:
        result.title = min(title_candidates, key=len)
    else:
        heading = next(
            (
                _clean(node.get_text(" ", strip=True))
                for node in detail.select("h1, h2, h3, h4")
                if len(_clean(node.get_text(" ", strip=True))) > 8
                and "exposé" not in _clean(node.get_text(" ", strip=True)).lower()
                and "übersicht" not in _clean(node.get_text(" ", strip=True)).lower()
            ),
            "",
        )
        result.title = heading or title_from_url_all(url)
    result.title = re.sub(r"^[A-Za-z0-9_-]+\s*»\s*", "", result.title).strip()
    _add_evidence(result, "title", result.title, "Peisser Exposé-Titel", result.title)

    description_match = re.search(
        r"Beschreibungen zum Inserat\s+Beschreibung\s+(.+?)(?=\s+(?:Lage|Ausstattung|Sonstige Angaben|Peisser Immobilien\s+Waldgasse)\b|$)",
        texts_text,
        re.I,
    )
    if description_match:
        result.description = _clean(description_match.group(1))
    elif texts_text:
        marker = texts_text.find("Beschreibungen zum Inserat")
        result.description = texts_text[marker + 27 :][:6000].strip() if marker >= 0 else None
    if result.description:
        _add_evidence(result, "description", result.description, "Peisser Beschreibung", result.description, "derived")

    price_match = re.search(r"Kaufpreis\s*:\s*([0-9][0-9\.\s]*(?:,[0-9]+)?)\s*EUR", detail_text, re.I)
    if price_match:
        parsed_price = _number(price_match.group(1))
        result.price_eur = int(round(parsed_price)) if parsed_price is not None else None
    _add_evidence(result, "price_eur", result.price_eur, "Peisser Kaufpreis", price_match.group(0) if price_match else None)

    result.living_area_m2, living_snippet = _label_number(detail_text, ("Wohnfläche", "Wohnnutzfläche"), r"m(?:²|2)")
    result.plot_area_m2, plot_snippet = _label_number(detail_text, ("Grundstücksfläche", "Grundfläche"), r"m(?:²|2)")
    result.rooms, rooms_snippet = _label_number(detail_text, ("Anzahl Zimmer", "Zimmer"))
    _add_evidence(result, "living_area_m2", result.living_area_m2, "Peisser Wohnfläche", living_snippet)
    _add_evidence(result, "plot_area_m2", result.plot_area_m2, "Peisser Grundstücksfläche", plot_snippet)
    _add_evidence(result, "rooms", result.rooms, "Peisser Zimmerzahl", rooms_snippet)

    address_match = re.search(r"Anschrift\s*:\s*(.+?)(?=\s+Region\s*:|\s+Details\b|$)", detail_text, re.I)
    if address_match:
        result.location_text = _clean(address_match.group(1))
        result.address_status = "municipality_only"
        _add_evidence(result, "location_text", result.location_text, "Peisser Anschrift", address_match.group(0))

    year_match = re.search(r"Baujahr\s*:\s*([12][0-9]{3})", all_text, re.I)
    if year_match:
        result.year_built = int(year_match.group(1))
        _add_evidence(result, "year_built", result.year_built, "Peisser Baujahr", year_match.group(0))

    heating_match = re.search(
        r"(?:Heizung|Heizungsart|Beheizung)\s*:?\s*([^|]{2,120}?)(?=\s+(?:Heizwärmebedarf|HWB|Gesamtenergie|f\s*GEE|Energieausweis|Warmwasser|Baujahr|Lage|Peisser Immobilien)\b|$)",
        all_text,
        re.I,
    )
    if heating_match:
        result.heating = _clean(heating_match.group(1)).strip(" ,;:-")[:120] or None
        _add_evidence(result, "heating", result.heating, "Peisser Heizung", heating_match.group(0), "derived")

    hwb_match = re.search(r"(?:Heizwärmebedarf(?:\s*\(in kWh/\(m²a\)\))?|HWB)\s*:?\s*([0-9]+(?:[\.,][0-9]+)?)", all_text, re.I)
    if hwb_match:
        result.energy_hwb = _number(hwb_match.group(1))
        _add_evidence(result, "energy_hwb", result.energy_hwb, "Peisser Heizwärmebedarf", hwb_match.group(0))

    fgee_match = re.search(r"(?:Gesamtenergieeffizienz-Faktor|f\s*GEE)\s*:?\s*([0-9]+(?:[\.,][0-9]+)?)", all_text, re.I)
    if fgee_match:
        result.energy_fgee = _number(fgee_match.group(1))
        _add_evidence(result, "energy_fgee", result.energy_fgee, "Peisser Gesamtenergieeffizienz", fgee_match.group(0))

    object_type = _object_type(detail_text)
    _add_evidence(result, "object_type", object_type, "Peisser Objektart", f"Objektart: {object_type}" if object_type else None)

    images: list[tuple[int, str]] = []
    for node in gallery.find_all(["a", "img"]):
        raw = node.get("href") or node.get("src")
        if not raw:
            continue
        absolute = urljoin(result.source_url, html_lib.unescape(str(raw)))
        match = re.search(rf"/data/{re.escape(str(entry_id or ''))}/img_([0-9]+)\.(?:jpe?g|png|webp)(?:\?|$)", absolute, re.I)
        if match:
            images.append((int(match.group(1)), absolute.split("?", 1)[0]))
    result.image_urls = [url for _, url in sorted(dict((url, index) for index, url in images).items(), key=lambda item: item[1])]

    if _sold_title(result.title):
        result.warnings.append("Peisser-Inserat ist als VERKAUFT gekennzeichnet")
    if result.price_eur is None:
        result.warnings.append("Peisser-Kaufpreis nicht numerisch angegeben")
    if result.living_area_m2 is None:
        result.warnings.append("Peisser-Wohnfläche nicht erkannt")
    if not result.image_urls:
        result.warnings.append("Keine Peisser-Galeriebilder erkannt")
    return result


async def _fetch_peisser_bundle(url: str) -> str:
    entry_id = peisser_entry_id(url)
    if not entry_id:
        if not _ORIGINAL_FETCH_HTML:
            raise RuntimeError("Kein HTTP-Abruf verfügbar")
        return await _ORIGINAL_FETCH_HTML(url)
    views = (("details", ""), ("texts", "&view=texts"), ("gallery", "&view=gallery"))
    parts: list[str] = []
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=BROWSER_HEADERS) as client:
        for name, suffix in views:
            response = await client.get(f"{PEISSER_BASE}expose.php?id={entry_id}{suffix}", headers={**BROWSER_HEADERS, "Referer": PEISSER_BASE})
            response.raise_for_status()
            page = BeautifulSoup(response.text, "html.parser")
            content = str(page.body or page)
            parts.append(f'<section data-peisser-view="{name}">{content}</section>')
    return "<html><body>" + "".join(parts) + "</body></html>"


async def fetch_html_all(url: str) -> str:
    if is_peisser_url(url) and peisser_entry_id(url):
        return await _fetch_peisser_bundle(url)
    if not _ORIGINAL_FETCH_HTML:
        raise RuntimeError("Kein ursprünglicher HTTP-Abruf verfügbar")
    return await _ORIGINAL_FETCH_HTML(url)


def parse_listing_all(url: str, raw_html: str) -> ParsedListing:
    if is_peisser_url(url):
        return parse_peisser(url, raw_html)
    if not _ORIGINAL_PARSE:
        return ParsedListing(source_name=provider_for_url_all(url), source_url=url)
    return _ORIGINAL_PARSE(url, raw_html)


def _overview_number(text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}\s*:\s*(?:ca\.\s*)?([0-9][0-9\.\s]*(?:,[0-9]+)?)", text, re.I)
    return _number(match.group(1)) if match else None


def parse_peisser_overview(raw_html: str, base_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(raw_html, "html.parser")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in soup.select("div.blog-post.padding-bottom-20, div.blog-post"):
        anchor = card.select_one("h3 a[href*='expose.php?id=']")
        if not anchor:
            continue
        absolute = urljoin(base_url, str(anchor.get("href") or ""))
        entry_id = peisser_entry_id(absolute)
        if not entry_id or entry_id in seen:
            continue
        seen.add(entry_id)
        raw_title = _clean(anchor.get_text(" ", strip=True))
        object_number = None
        title = raw_title
        split = re.match(r"^([A-Za-z0-9_-]+)\s*»\s*(.+)$", raw_title)
        if split:
            object_number, title = split.group(1), split.group(2)
        card_text = _clean(card.get_text(" ", strip=True))
        image = card.select_one("img[src]")
        preview = urljoin(base_url, str(image.get("src"))) if image and image.get("src") else None
        object_type_match = re.search(r"\b(Einfamilienhaus|Mehrfamilienhaus|Wohnimmobilie|Wohngrundstück|Grundstück|Landwirtschaft|Wohnung|Haus)\s+Kauf\b", card_text, re.I)
        location_match = re.search(r"\bKauf\s+([1-9][0-9]{3}\s+.+?)\s+Österreich\b", card_text, re.I)
        price_match = re.search(r"Kaufpreis\s*:\s*([0-9][0-9\.\s]*(?:,[0-9]+)?)\s*EUR", card_text, re.I)
        result.append(
            {
                "entry_id": entry_id,
                "object_number": object_number,
                "url": canonical_listing_url_all(absolute),
                "title": title,
                "raw_title": raw_title,
                "sold": _sold_title(raw_title),
                "object_type": _clean(object_type_match.group(1)) if object_type_match else None,
                "location_text": _clean(location_match.group(1)) if location_match else None,
                "price_eur": int(round(_number(price_match.group(1)))) if price_match and _number(price_match.group(1)) is not None else None,
                "living_area_m2": _overview_number(card_text, "Wohnfläche"),
                "plot_area_m2": _overview_number(card_text, "Grundstücksfläche"),
                "rooms": _overview_number(card_text, "Anzahl Zimmer"),
                "preview_image_url": preview,
            }
        )
    return result


def _allowed_postcodes(profile: dict[str, Any]) -> set[str]:
    return set(re.findall(r"\b[1-9][0-9]{3}\b", str(profile.get("area_ids") or "")))


def _overview_allowed(profile: dict[str, Any], item: dict[str, Any]) -> bool:
    if item.get("sold"):
        return False
    object_type = _normalize(item.get("object_type"))
    if object_type and object_type not in HOUSE_TYPES:
        return False
    allowed = _allowed_postcodes(profile)
    location = str(item.get("location_text") or "")
    postcode_match = re.search(r"\b[1-9][0-9]{3}\b", location)
    if allowed and postcode_match and postcode_match.group(0) not in allowed:
        return False
    try:
        max_price = float(profile.get("max_price_eur") or 0)
    except Exception:
        max_price = 0
    if max_price and item.get("price_eur") is not None and float(item["price_eur"]) > max_price:
        return False
    try:
        min_living = float(profile.get("min_living_area_m2") or 0)
    except Exception:
        min_living = 0
    if min_living and item.get("living_area_m2") is not None and float(item["living_area_m2"]) < min_living:
        return False
    return True


def _evaluate_local(profile: dict[str, Any], parsed: ParsedListing, raw_html: str) -> tuple[str, list[str]]:
    status, reasons = main.evaluate_candidate(profile, parsed)
    detail_text = _clean(BeautifulSoup(raw_html, "html.parser").get_text(" ", strip=True))
    object_type = _normalize(_object_type(detail_text))
    if object_type and object_type not in HOUSE_TYPES:
        return "filtered", [f"Objektart {object_type} ist kein Haus"] + reasons
    allowed = _allowed_postcodes(profile)
    postcode = re.search(r"\b[1-9][0-9]{3}\b", str(parsed.location_text or ""))
    if allowed and postcode and postcode.group(0) not in allowed:
        return "filtered", [f"PLZ {postcode.group(0)} liegt außerhalb des Suchprofils"] + reasons
    if _sold_title(parsed.title):
        return "filtered", ["Inserat ist als VERKAUFT gekennzeichnet"]
    return status, reasons


def _mark_existing_sold(item: dict[str, Any]) -> None:
    with connect() as con:
        con.execute(
            """
            UPDATE search_candidates
            SET status = 'offline', decision = 'sold', offline_at = COALESCE(offline_at, ?),
                filter_reasons = ?, last_seen_at = ?
            WHERE source_url = ?
            """,
            (now_iso(), json.dumps(["Peisser-Inserat ist als VERKAUFT gekennzeichnet"], ensure_ascii=False), now_iso(), item["url"]),
        )
        con.commit()


async def run_peisser_search(profile_id: str, max_results: int = 80) -> int:
    profile = get_search_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Suchprofil nicht gefunden")
    limit = max(1, min(int(max_results or 80), 160))
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    page_signatures: set[tuple[str, ...]] = set()

    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=BROWSER_HEADERS) as client:
        for page in range(1, PEISSER_MAX_PAGES + 1):
            page_url = f"{PEISSER_BASE}index.php?page={page}&view=index&mode=entry&lang=de"
            response = await client.get(page_url, headers={**BROWSER_HEADERS, "Referer": PEISSER_BASE})
            response.raise_for_status()
            items = parse_peisser_overview(response.text, str(response.url))
            signature = tuple(sorted(str(item["entry_id"]) for item in items))
            if not items or signature in page_signatures:
                break
            page_signatures.add(signature)
            for item in items:
                if item.get("sold"):
                    _mark_existing_sold(item)
                    continue
                if item["entry_id"] in seen_ids:
                    continue
                seen_ids.add(item["entry_id"])
                if _overview_allowed(profile, item):
                    selected.append(item)
                if len(selected) >= limit:
                    break
            if len(selected) >= limit:
                break

    for item in selected:
        try:
            raw_html = await _fetch_peisser_bundle(item["url"])
            parsed = parse_peisser(item["url"], raw_html)
            if _sold_title(parsed.title):
                _mark_existing_sold(item)
                continue
            status, reasons = _evaluate_local(profile, parsed, raw_html)
            upsert_search_candidate(
                profile_id,
                parsed.source_url,
                parsed.title,
                status=status,
                facts=main.facts_from_parsed(parsed),
                filter_reasons=reasons,
            )
        except Exception as exc:
            upsert_search_candidate(
                profile_id,
                item["url"],
                item.get("title") or title_from_url_all(item["url"]),
                status="review",
                facts={
                    "price_eur": item.get("price_eur"),
                    "living_area_m2": item.get("living_area_m2"),
                    "plot_area_m2": item.get("plot_area_m2"),
                    "preview_image_url": item.get("preview_image_url"),
                },
                filter_reasons=[f"Peisser-Detailprüfung fehlgeschlagen: {str(exc)[:300]}"],
            )
    update_search_profile_run(profile_id, len(selected))
    return len(selected)


async def run_search_all(profile_id: str, max_results: int = 80) -> int:
    profile = get_search_profile(profile_id)
    if profile and str(profile.get("source_name") or "") == PEISSER_SOURCE:
        return await run_peisser_search(profile_id, max_results)
    if not _ORIGINAL_RUN_SEARCH:
        return 0
    return await _ORIGINAL_RUN_SEARCH(profile_id, max_results)


def resolve_search_urls_all(profile: dict[str, Any]) -> list[str]:
    if str(profile.get("source_name") or "") == PEISSER_SOURCE:
        urls = dynamic._split_urls(profile.get("search_url"))
        if str(profile.get("search_url_mode") or "automatic") == "custom" and urls:
            return urls
        return [PEISSER_SEARCH_URL]
    return _ORIGINAL_RESOLVE_URLS(profile) if _ORIGINAL_RESOLVE_URLS else []


def validate_search_profile_all(source_name: str, search_url: str, profile_data: dict[str, Any], area_ids: str | None) -> tuple[str, str]:
    if source_name == PEISSER_SOURCE:
        raw_url = str(search_url or "").strip()
        profile_data["search_url_mode"] = "custom" if raw_url else "automatic"
        if raw_url:
            if not raw_url.startswith(("http://", "https://")) or not is_peisser_url(raw_url):
                raise HTTPException(status_code=400, detail="Die eigene Peisser-Such-URL ist ungültig")
            return PEISSER_SOURCE, raw_url
        return PEISSER_SOURCE, PEISSER_SEARCH_URL
    if not _ORIGINAL_VALIDATE:
        return support.WILLHABEN_SOURCE, search_url
    return _ORIGINAL_VALIDATE(source_name, search_url, profile_data, area_ids)


def _is_auto_url_all(provider: str, url: str) -> bool:
    if provider == PEISSER_SOURCE:
        parts = urlsplit(url)
        return is_peisser_url(url) and parts.path.endswith("index.php")
    return dynamic._is_auto_url_original(provider, url) if hasattr(dynamic, "_is_auto_url_original") else False


def profile_form_all(profile: dict[str, Any] | None = None, action: str = "") -> str:
    if not _ORIGINAL_FORM:
        return ""
    html = _ORIGINAL_FORM(profile, action)
    provider = str((profile or {}).get("source_name") or support.WILLHABEN_SOURCE)
    selected = "selected" if provider == PEISSER_SOURCE else ""
    if f'value="{PEISSER_SOURCE}"' not in html:
        html = html.replace(
            '</select>',
            f'<option value="{PEISSER_SOURCE}" {selected}>Peisser Immobilien</option></select>',
            1,
        )
    html = html.replace(
        "Ohne eigene URL erzeugt HausCheck je PLZ automatisch eine passende Portal-Suche.",
        "Willhaben und ImmobilienScout werden per PLZ gesucht. Bei Peisser prüft HausCheck automatisch Seiten 1 bis 10 und filtert PLZ, Preis und Fläche lokal.",
    )
    marker = "if (field('source_name').value === 'immobilienscout24.at') {"
    replacement = f"""if (field('source_name').value === '{PEISSER_SOURCE}') {{
          url = '{PEISSER_SEARCH_URL}';
          preview.textContent = 'Automatisch: Peisser Seiten 1 bis 10 · Abbruch bei leerer oder wiederholter Seite · Filter lokal';
          return;
        }} else if (field('source_name').value === 'immobilienscout24.at') {{"""
    html = html.replace(marker, replacement)
    return html


def profile_card_all(profile: dict[str, Any]) -> str:
    if not _ORIGINAL_PROFILE_CARD:
        return ""
    html = _ORIGINAL_PROFILE_CARD(profile)
    if str(profile.get("source_name") or "") == PEISSER_SOURCE:
        html = html.replace("<strong>Portal:</strong> Willhaben", "<strong>Portal:</strong> Peisser Immobilien")
        html = html.replace("+ 0 weitere PLZ-Suche(n)", "")
    return html


async def remote_image_hashes_all(urls: list[str], limit: int = 5) -> list[str]:
    if not any(is_peisser_url(url) for url in urls):
        return await _ORIGINAL_REMOTE_HASHES(urls, limit) if _ORIGINAL_REMOTE_HASHES else []
    result: list[str] = []
    headers = {"User-Agent": BROWSER_HEADERS["User-Agent"], "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Referer": PEISSER_BASE}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
        for url in urls[: max(1, limit)]:
            try:
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > 20 * 1024 * 1024:
                    continue
                image_hash = support._dhash(response.content)
                if image_hash and image_hash not in result:
                    result.append(image_hash)
            except Exception:
                continue
    return result


async def import_listing_all(url: str, preview_image_url: str | None = None) -> dict[str, Any]:
    if not is_peisser_url(url):
        if not _ORIGINAL_IMPORT:
            raise RuntimeError("Kein Importhandler verfügbar")
        return await _ORIGINAL_IMPORT(url, preview_image_url)

    import app.github_auto_export as github_auto_export
    import app.gmail_exchange as gmail_exchange
    import app.house_manage as house_manage

    raw_html = await _fetch_peisser_bundle(url)
    parsed = parse_peisser(url, raw_html)
    if _sold_title(parsed.title):
        raise HTTPException(status_code=409, detail="Dieses Peisser-Inserat ist als VERKAUFT gekennzeichnet")

    existing = support.find_existing_house_for_source(url, parsed)
    duplicate_method = "same_source" if existing else None
    duplicate_score = 100.0 if existing else 0.0
    duplicate_details: dict[str, Any] = {}
    if not existing:
        existing, duplicate_method, duplicate_score, duplicate_details = await support.find_probable_duplicate(parsed)
    created = existing is None
    if created:
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
        set_pipeline_stage(str(house["id"]), "created", "ok", "Hausakte wurde angelegt.")
    else:
        house = existing or {}
        support._record_duplicate(str(house["id"]), parsed, duplicate_method or "duplicate", duplicate_score, duplicate_details)
        set_pipeline_stage(str(house["id"]), "source_merged", "ok", "Peisser-Inserat wurde einer vorhandenen Hausakte zugeordnet.")

    house_id = str(house["id"])
    house_manage.set_house_preview(house_id, preview_image_url or (parsed.image_urls[0] if parsed.image_urls else None))
    source, same_source = support._store_or_refresh_source(house_id, parsed, raw_html)
    support._update_house_from_source(house_id, parsed, same_source=same_source)
    add_evidence(house_id, str(source.get("id") or ""), parsed.evidence)
    mark_candidates_imported(parsed.source_url, house_id)
    support._queue_media(house_id, str(source.get("id") or ""), parsed)
    set_pipeline_stage(house_id, "media_loading", "running", "Peisser-Bilder werden geladen.")
    await main.download_pending_media_files(house_id)
    support.dedupe_house_images_perceptually(house_id)
    media = list_media(house_id)
    downloaded = len([item for item in media if item.get("download_status") == "downloaded"])
    failed = len([item for item in media if item.get("download_status") == "failed"])
    set_pipeline_stage(
        house_id,
        "media_ready",
        "ok" if downloaded else "error",
        f"Medienabruf abgeschlossen: {downloaded} geladen, {failed} fehlgeschlagen.",
        error=None if downloaded else "Keine Medien konnten geladen werden.",
    )
    await github_auto_export.auto_export_house_to_github(house_id)
    await gmail_exchange.send_analysis_zip_via_gmail(house_id)
    return {"house": get_house(house_id) or house, "created": created, "duplicate": not created, "duplicate_method": duplicate_method}


def register_peisser_support(app: FastAPI) -> None:
    global _PATCHED
    global _ORIGINAL_PROVIDER, _ORIGINAL_EXTERNAL_ID, _ORIGINAL_CANONICAL, _ORIGINAL_PARSE, _ORIGINAL_FETCH_HTML
    global _ORIGINAL_RESOLVE_URLS, _ORIGINAL_VALIDATE, _ORIGINAL_FORM, _ORIGINAL_PROFILE_CARD
    global _ORIGINAL_RUN_SEARCH, _ORIGINAL_IMPORT, _ORIGINAL_REMOTE_HASHES
    if _PATCHED:
        return

    _ORIGINAL_PROVIDER = support.provider_for_url
    _ORIGINAL_EXTERNAL_ID = support.external_id_for_url
    _ORIGINAL_CANONICAL = support.canonical_listing_url
    _ORIGINAL_PARSE = main.parse_listing
    _ORIGINAL_FETCH_HTML = main.fetch_html
    _ORIGINAL_RESOLVE_URLS = main.resolve_search_urls
    _ORIGINAL_VALIDATE = dynamic.validate_search_profile_url_dynamic
    _ORIGINAL_FORM = modern_ui._profile_form
    _ORIGINAL_PROFILE_CARD = lifecycle_ui._profile_card
    _ORIGINAL_RUN_SEARCH = search_automation.run_search_profile
    _ORIGINAL_IMPORT = import_patch.import_listing_to_pipeline
    _ORIGINAL_REMOTE_HASHES = support._remote_image_hashes

    if not hasattr(dynamic, "_is_auto_url_original"):
        dynamic._is_auto_url_original = dynamic._is_auto_url
    dynamic._is_auto_url = _is_auto_url_all

    support.provider_for_url = provider_for_url_all
    support.external_id_for_url = external_id_for_url_all
    support.canonical_listing_url = canonical_listing_url_all
    support.parse_listing_multi = parse_listing_all
    support.title_from_listing_url_multi = title_from_url_all
    support._remote_image_hashes = remote_image_hashes_all

    main.fetch_html = fetch_html_all
    main.parse_listing = parse_listing_all
    main.title_from_listing_url = title_from_url_all
    parser_module.parse_listing = parse_listing_all

    dynamic.validate_search_profile_url_dynamic = validate_search_profile_all
    support._validate_search_profile_url = validate_search_profile_all
    dynamic.resolve_search_urls_dynamic = resolve_search_urls_all
    dynamic.resolve_search_url_dynamic = lambda profile: "\n".join(resolve_search_urls_all(profile))
    main.resolve_search_urls = resolve_search_urls_all
    main.resolve_search_url = lambda profile: "\n".join(resolve_search_urls_all(profile))

    dynamic._profile_form = profile_form_all
    runtime_fix._profile_form_integer = profile_form_all
    modern_ui._profile_form = profile_form_all
    lifecycle_ui._new_profile_form = lambda: profile_form_all(None, "profiles")
    lifecycle_ui._profile_card = profile_card_all

    search_automation.run_search_profile = run_search_all
    main.run_search_profile = run_search_all
    import_patch.import_listing_to_pipeline = import_listing_all
    search_automation.import_listing_to_pipeline = import_listing_all
    support.import_listing_to_pipeline_multi = import_listing_all

    _PATCHED = True
