from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse
from PIL import Image, UnidentifiedImageError

import app.parser as parser_module
from app.parser import ParsedListing, SearchResultCandidate
from app.storage import (
    PROJECTS_DIR,
    add_evidence,
    add_media,
    connect,
    create_house,
    create_search_profile,
    create_source,
    ensure_columns,
    get_house,
    list_houses,
    list_media,
    list_sources,
    mark_candidates_imported,
    now_iso,
    project_dir,
    row_to_dict,
)


IMMOSCOUT_SOURCE = "immobilienscout24.at"
WILLHABEN_SOURCE = "willhaben.at"
IMMOSCOUT_HOST_MARKERS = ("immobilienscout24.at", "immobilienscout24.de")
IMMOSCOUT_IMAGE_HOST = "pictures.immobilienscout24.de"
_PATCHED = False

_ORIGINAL_PARSE_LISTING: Callable[[str, str], ParsedListing] | None = None
_ORIGINAL_EXTRACT_CANDIDATES: Callable[[str, str], list[SearchResultCandidate]] | None = None
_ORIGINAL_TITLE_FROM_URL: Callable[[str], str] | None = None
_ORIGINAL_DOWNLOAD_MEDIA: Callable[..., Awaitable[None]] | None = None
_ORIGINAL_SYNC_CANDIDATES: Callable[[str], None] | None = None
_ORIGINAL_PROFILE_CARD: Callable[[dict[str, Any]], str] | None = None


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _host(url: str) -> str:
    return urlsplit(str(url or "")).netloc.lower().split(":", 1)[0]


def is_immoscout_url(url: str) -> bool:
    host = _host(url)
    return any(marker in host for marker in IMMOSCOUT_HOST_MARKERS)


def provider_for_url(url: str) -> str:
    host = _host(url)
    if "willhaben.at" in host:
        return WILLHABEN_SOURCE
    if is_immoscout_url(url):
        return IMMOSCOUT_SOURCE
    return host or "unknown"


def external_id_for_url(url: str) -> str | None:
    if is_immoscout_url(url):
        match = re.search(r"/expose/([A-Za-z0-9_-]+)(?:$|[/?#])", str(url or ""), re.I)
        return match.group(1) if match else None
    match = re.search(r"-(\d{7,})(?:$|[/?#])", str(url or ""))
    return match.group(1) if match else None


def canonical_listing_url(url: str) -> str:
    raw = html_lib.unescape(str(url or "")).replace("\\/", "/").strip()
    parts = urlsplit(raw)
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/")
    if is_immoscout_url(raw):
        match = re.search(r"/expose/([A-Za-z0-9_-]+)", path, re.I)
        if match:
            path = f"/expose/{match.group(1)}"
    elif "willhaben.at" in parts.netloc.lower():
        path = path
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, "", ""))


def title_from_listing_url_multi(url: str) -> str:
    if is_immoscout_url(url):
        expose_id = external_id_for_url(url)
        return f"ImmobilienScout24 Exposé {expose_id}" if expose_id else "ImmobilienScout24 Inserat"
    if _ORIGINAL_TITLE_FROM_URL:
        return _ORIGINAL_TITLE_FROM_URL(url)
    return str(url or "")


def _number(value: object) -> float | None:
    text = re.sub(r"[^0-9,.-]", "", str(value or "").replace("\u00a0", " ")).strip()
    if not text or text in {"-", ".", ","}:
        return None
    negative = text.startswith("-")
    text = text.lstrip("-")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        left, right = text.rsplit(",", 1)
        text = left.replace(",", "") + ("." + right if right else "")
    elif "." in text:
        chunks = text.split(".")
        if len(chunks) > 2 or (len(chunks[-1]) == 3 and len(chunks[0]) <= 3):
            text = "".join(chunks)
    try:
        value_float = float(text)
        return -value_float if negative else value_float
    except ValueError:
        return None


def _int(value: object) -> int | None:
    parsed = _number(value)
    return int(round(parsed)) if parsed is not None else None


def _meta_content(soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None) -> str | None:
    attrs: dict[str, str] = {}
    if property_name:
        attrs["property"] = property_name
    if name:
        attrs["name"] = name
    node = soup.find("meta", attrs=attrs)
    if node and node.get("content"):
        return str(node.get("content")).strip()
    return None


def _json_ld_graph(soup: BeautifulSoup) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        candidates: list[Any]
        if isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
            candidates = payload["@graph"]
        elif isinstance(payload, list):
            candidates = payload
        else:
            candidates = [payload]
        result.extend(item for item in candidates if isinstance(item, dict))
    return result


def _type_has(item: dict[str, Any], expected: str) -> bool:
    value = item.get("@type")
    if isinstance(value, list):
        return expected in value
    return str(value or "") == expected


def _clean_description(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = html_lib.unescape(str(value or "")).replace("\\/", "/").strip()
        if not normalized:
            continue
        if normalized.startswith("//"):
            normalized = "https:" + normalized
        if not normalized.startswith(("http://", "https://")):
            continue
        if IMMOSCOUT_IMAGE_HOST in _host(normalized):
            parts = urlsplit(normalized)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            if "q" in query:
                query["q"] = "85"
            normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        key = normalized
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


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


def _label_value(text: str, labels: tuple[str, ...], *, unit: str | None = None) -> tuple[float | None, str | None]:
    joined = "|".join(labels)
    unit_pattern = rf"\s*{unit}" if unit else ""
    pattern = rf"(?:{joined})\s*:?[\s\-]*([0-9][0-9\.\s]*(?:,[0-9]+)?|[0-9]+(?:\.[0-9]+)?){unit_pattern}"
    match = re.search(pattern, text, re.I)
    if not match:
        return None, None
    return _number(match.group(1)), match.group(0)


def parse_immoscout(url: str, raw_html: str) -> ParsedListing:
    soup = BeautifulSoup(raw_html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    expose_id = external_id_for_url(url)
    result = ParsedListing(source_name=IMMOSCOUT_SOURCE, source_url=canonical_listing_url(url), external_id=expose_id)
    graph = _json_ld_graph(soup)
    web_page = next((item for item in graph if _type_has(item, "WebPage")), {})
    product = next((item for item in graph if _type_has(item, "Product")), {})
    estate = next((item for item in graph if _type_has(item, "RealEstateListing")), {})

    title = str(estate.get("name") or product.get("name") or web_page.get("name") or _meta_content(soup, property_name="og:title") or "").strip()
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    if title:
        result.title = title
        _add_evidence(result, "title", title, "ImmobilienScout JSON-LD/og:title", title)

    descriptions = [
        _clean_description(estate.get("description")),
        _clean_description(product.get("description")),
        _clean_description(web_page.get("description")),
        _clean_description(_meta_content(soup, property_name="og:description")),
        _clean_description(_meta_content(soup, name="description")),
    ]
    descriptions = [item for item in descriptions if item]
    result.description = max(descriptions, key=len) if descriptions else None
    if result.description:
        _add_evidence(result, "description", result.description, "ImmobilienScout JSON-LD", result.description, "derived")

    offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    result.price_eur = _int(offers.get("price"))
    if result.price_eur is None:
        price, snippet = _label_value(text, ("Kaufpreis", "Preis"))
        result.price_eur = int(price) if price is not None and price >= 1000 else None
    else:
        snippet = f"Offer price {offers.get('price')} {offers.get('priceCurrency') or 'EUR'}"
    _add_evidence(result, "price_eur", result.price_eur, "ImmobilienScout JSON-LD Offer", snippet)

    floor_size = estate.get("floorSize") if isinstance(estate.get("floorSize"), dict) else {}
    result.living_area_m2 = _number(floor_size.get("value"))
    if result.living_area_m2 is None:
        result.living_area_m2, living_snippet = _label_value(text, ("Wohnfläche", "Wohnnutzfläche"), unit=r"m(?:²|2)")
    else:
        living_snippet = f"floorSize {floor_size.get('value')} {floor_size.get('unitCode') or ''}"
    _add_evidence(result, "living_area_m2", result.living_area_m2, "ImmobilienScout JSON-LD floorSize", living_snippet)

    result.plot_area_m2, plot_snippet = _label_value(text, ("Grundstücksfläche", "Grundfläche", "Grundstück"), unit=r"m(?:²|2)")
    _add_evidence(result, "plot_area_m2", result.plot_area_m2, "ImmobilienScout Merkmal Grundstücksfläche", plot_snippet)

    result.rooms = _number(estate.get("numberOfRooms"))
    if result.rooms is None:
        result.rooms, rooms_snippet = _label_value(text, ("Zimmer",))
    else:
        rooms_snippet = f"numberOfRooms {estate.get('numberOfRooms')}"
    _add_evidence(result, "rooms", result.rooms, "ImmobilienScout JSON-LD numberOfRooms", rooms_snippet)

    year_match = re.search(r"Baujahr\s*:?[\s\-]*([12][0-9]{3}|-)", text, re.I)
    if year_match and year_match.group(1) != "-":
        result.year_built = int(year_match.group(1))
        _add_evidence(result, "year_built", result.year_built, "ImmobilienScout Merkmal Baujahr", year_match.group(0))

    heating_match = re.search(
        r"(?:Heizung|Heizungsart)\s*:?[\s\-]*([^|]{1,100}?)(?=\s+(?:Heizwärmebedarf|HWB|Gesamtenergie|f\s*GEE|Energieausweis|Beschreibung|Ausstattung|Baujahr|Objektbeschreibung)\b|$)",
        text,
        re.I,
    )
    if heating_match:
        result.heating = re.sub(r"\s+", " ", heating_match.group(1)).strip(" ,;:-")[:120] or None
        _add_evidence(result, "heating", result.heating, "ImmobilienScout Merkmal Heizung", heating_match.group(0), "derived")

    hwb_match = re.search(r"(?:Heizwärmebedarf\s*\(HWB\)|Heizwärmebedarf|HWB)\s*:?[\s\-]*([0-9]+(?:[\.,][0-9]+)?)", text, re.I)
    if hwb_match:
        result.energy_hwb = _number(hwb_match.group(1))
        _add_evidence(result, "energy_hwb", result.energy_hwb, "ImmobilienScout Energiekennzahl HWB", hwb_match.group(0))
        class_match = re.search(re.escape(hwb_match.group(0)) + r"[^A-G]{0,30}\b([A-G])\b", text[hwb_match.start():hwb_match.end() + 80], re.I)
        if class_match:
            result.energy_class_hwb = class_match.group(1).upper()

    fgee_match = re.search(r"(?:Gesamtenergieeffizienz(?:-Faktor)?\s*\(f\s*GEE\)|f\s*GEE)\s*:?[\s\-]*([0-9]+(?:[\.,][0-9]+)?)", text, re.I)
    if fgee_match:
        result.energy_fgee = _number(fgee_match.group(1))
        _add_evidence(result, "energy_fgee", result.energy_fgee, "ImmobilienScout Energiekennzahl fGEE", fgee_match.group(0))

    address = estate.get("address") if isinstance(estate.get("address"), dict) else {}
    street = str(address.get("streetAddress") or "").strip()
    postcode = str(address.get("postalCode") or "").strip()
    city = str(address.get("addressLocality") or "").strip()
    if street:
        result.location_text = ", ".join(part for part in (street, f"{postcode} {city}".strip()) if part)
        result.address_status = "exact"
    elif postcode or city:
        result.location_text = " ".join(part for part in (postcode, city) if part)
        result.address_status = "municipality_only"
    if result.location_text:
        _add_evidence(result, "location_text", result.location_text, "ImmobilienScout JSON-LD PostalAddress", json.dumps(address, ensure_ascii=False))

    images: list[str] = []
    product_images = product.get("image")
    if isinstance(product_images, list):
        images.extend(str(item) for item in product_images)
    elif product_images:
        images.append(str(product_images))
    estate_images = estate.get("image")
    if isinstance(estate_images, list):
        images.extend(str(item) for item in estate_images)
    elif estate_images:
        images.append(str(estate_images))
    og_image = _meta_content(soup, property_name="og:image")
    if og_image:
        images.append(og_image)
    result.image_urls = _ordered_unique(images)

    if result.price_eur is None:
        result.warnings.append("ImmobilienScout-Kaufpreis nicht sicher erkannt")
    if result.living_area_m2 is None:
        result.warnings.append("ImmobilienScout-Wohnfläche nicht sicher erkannt")
    if result.plot_area_m2 is None:
        result.warnings.append("ImmobilienScout-Grundstücksfläche nicht sicher erkannt")
    if not result.image_urls:
        result.warnings.append("Keine ImmobilienScout-Galeriebilder erkannt")
    return result


def _candidate_preview(container: Any, base_url: str) -> str | None:
    if container is None:
        return None
    for node in container.select("img, source"):
        candidates: list[str] = []
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "srcset", "data-srcset"):
            raw = node.get(attr)
            if not raw:
                continue
            for part in str(raw).split(","):
                candidates.append(part.strip().split(" ", 1)[0])
        for candidate in candidates:
            absolute = urljoin(base_url, html_lib.unescape(candidate).replace("\\/", "/"))
            if IMMOSCOUT_IMAGE_HOST in _host(absolute):
                return _ordered_unique([absolute])[0]
    raw_html = str(container)
    matches = re.findall(r"https?:\\?/\\?/pictures\.immobilienscout24\.de[^\"'\s<>]+", raw_html, re.I)
    if matches:
        return _ordered_unique([matches[0].replace("\\/", "/")])[0]
    return None


def extract_immoscout_candidates(raw_html: str, base_url: str) -> list[SearchResultCandidate]:
    soup = BeautifulSoup(raw_html, "html.parser")
    by_id: dict[str, SearchResultCandidate] = {}

    def add(raw_href: str, title: str | None = None, preview: str | None = None) -> None:
        absolute = urljoin(base_url, html_lib.unescape(str(raw_href or "")).replace("\\/", "/"))
        expose_id = external_id_for_url(absolute)
        if not expose_id:
            return
        normalized = canonical_listing_url(absolute)
        current = by_id.get(expose_id)
        if current is None:
            by_id[expose_id] = SearchResultCandidate(url=normalized, title=title, preview_image_url=preview)
            return
        if title and not current.title:
            current.title = title
        if preview and not current.preview_image_url:
            current.preview_image_url = preview

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if not re.search(r"/expose/[A-Za-z0-9_-]+", href, re.I):
            continue
        container = anchor
        for _ in range(8):
            parent = getattr(container, "parent", None)
            if parent is None or getattr(parent, "name", None) in {"body", "html"}:
                break
            container = parent
            if _candidate_preview(container, base_url):
                break
        title_node = None
        if container is not None:
            title_node = container.select_one("h1, h2, h3, [data-testid*='title'], [class*='title']")
        title = (title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True)) or None
        add(href, title=title, preview=_candidate_preview(container, base_url))

    for match in re.finditer(r"(?:https?:\\?/\\?/(?:www\.)?immobilienscout24\.at)?/expose/([A-Za-z0-9_-]+)", raw_html, re.I):
        add(f"https://www.immobilienscout24.at/expose/{match.group(1)}")

    return list(by_id.values())


def extract_listing_candidates_multi(raw_html: str, base_url: str) -> list[SearchResultCandidate]:
    if is_immoscout_url(base_url):
        return extract_immoscout_candidates(raw_html, base_url)
    if _ORIGINAL_EXTRACT_CANDIDATES:
        return _ORIGINAL_EXTRACT_CANDIDATES(raw_html, base_url)
    return []


def extract_listing_links_multi(raw_html: str, base_url: str) -> list[str]:
    return sorted(candidate.url for candidate in extract_listing_candidates_multi(raw_html, base_url))


def parse_listing_multi(url: str, raw_html: str) -> ParsedListing:
    if is_immoscout_url(url):
        return parse_immoscout(url, raw_html)
    if _ORIGINAL_PARSE_LISTING:
        return _ORIGINAL_PARSE_LISTING(url, raw_html)
    return ParsedListing(source_name=provider_for_url(url), source_url=url)


def listing_key_multi(url: str) -> str:
    provider = provider_for_url(url)
    external_id = external_id_for_url(url)
    if external_id:
        return f"{provider}:{external_id}"
    return canonical_listing_url(url).lower()


def source_url_exists_multi(source_url: str) -> bool:
    canonical = canonical_listing_url(source_url)
    provider = provider_for_url(source_url)
    external_id = external_id_for_url(source_url)
    with connect() as con:
        rows = con.execute("SELECT source_name, source_url, external_id FROM listing_sources").fetchall()
    for row in rows:
        if canonical_listing_url(str(row["source_url"] or "")) == canonical:
            return True
        if external_id and str(row["external_id"] or "") == external_id and str(row["source_name"] or "") == provider:
            return True
    return False


def ensure_immoscout_schema() -> None:
    with connect() as con:
        ensure_columns(con, "media_assets", {"perceptual_hash": "TEXT"})
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS duplicate_match_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                house_id TEXT NOT NULL,
                source_url TEXT NOT NULL,
                provider TEXT,
                external_id TEXT,
                match_method TEXT NOT NULL,
                match_score REAL,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_listing_sources_provider_external ON listing_sources(source_name, external_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_media_perceptual_hash ON media_assets(perceptual_hash)")
        con.commit()


def _dhash(content: bytes) -> str | None:
    try:
        with Image.open(BytesIO(content)) as image:
            image = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
            if len(set(pixels)) < 8:
                return None
            value = 0
            for row in range(8):
                offset = row * 9
                for col in range(8):
                    value = (value << 1) | int(pixels[offset + col] > pixels[offset + col + 1])
            return f"{value:016x}"
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _hash_distance(left: str | None, right: str | None) -> int:
    if not left or not right:
        return 999
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except Exception:
        return 999


def _local_media_hashes(house_id: str, limit: int = 12) -> list[str]:
    ensure_immoscout_schema()
    result: list[str] = []
    for media in list_media(house_id):
        if media.get("kind") != "image" or media.get("download_status") != "downloaded" or not media.get("local_path"):
            continue
        phash = str(media.get("perceptual_hash") or "").strip() or None
        path = Path(str(media.get("local_path")))
        try:
            path.resolve().relative_to(PROJECTS_DIR.resolve())
        except Exception:
            continue
        if not phash and path.exists():
            try:
                phash = _dhash(path.read_bytes())
            except Exception:
                phash = None
            if phash:
                with connect() as con:
                    con.execute("UPDATE media_assets SET perceptual_hash = ? WHERE id = ?", (phash, media.get("id")))
                    con.commit()
        if phash and phash not in result:
            result.append(phash)
        if len(result) >= limit:
            break
    return result


async def _remote_image_hashes(urls: list[str], limit: int = 5) -> list[str]:
    result: list[str] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.immobilienscout24.at/",
    }
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
        for url in urls[: max(1, limit)]:
            try:
                response = await client.get(url)
                response.raise_for_status()
                if len(response.content) > 20 * 1024 * 1024:
                    continue
                phash = _dhash(response.content)
                if phash and phash not in result:
                    result.append(phash)
            except Exception:
                continue
    return result


def _normalize_text(value: object) -> str:
    text = str(value or "").lower()
    text = text.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _location_key(value: object) -> str:
    text = _normalize_text(value)
    postcode = re.search(r"\b[1-9][0-9]{3}\b", text)
    tokens = [token for token in text.split() if not re.fullmatch(r"[0-9]+[a-z]?", token)]
    return " ".join(([postcode.group(0)] if postcode else []) + tokens[-4:])


def _close_number(left: object, right: object, relative: float, absolute: float) -> bool:
    try:
        a, b = float(left), float(right)
    except Exception:
        return False
    return abs(a - b) <= max(absolute, max(abs(a), abs(b)) * relative)


def _title_similarity(left: object, right: object) -> float:
    a = _normalize_text(left)
    b = _normalize_text(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _structured_match(house: dict[str, Any], parsed: ParsedListing) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    existing_location = _location_key(house.get("location_text"))
    parsed_location = _location_key(parsed.location_text)
    if existing_location and parsed_location and existing_location == parsed_location:
        score += 1.0
        reasons.append("gleicher Ort/PLZ")
    exact_existing = str(house.get("address_status") or "") == "exact"
    exact_new = parsed.address_status == "exact"
    if exact_existing and exact_new and _normalize_text(house.get("location_text")) == _normalize_text(parsed.location_text):
        score += 6.0
        reasons.append("identische bestätigte Adresse")
    if _close_number(house.get("living_area_m2"), parsed.living_area_m2, 0.03, 3.0):
        score += 2.0
        reasons.append("gleiche Wohnfläche")
    if _close_number(house.get("plot_area_m2"), parsed.plot_area_m2, 0.04, 20.0):
        score += 2.0
        reasons.append("gleiche Grundstücksfläche")
    if _close_number(house.get("rooms"), parsed.rooms, 0.0, 0.1):
        score += 1.0
        reasons.append("gleiche Zimmerzahl")
    if house.get("year_built") and parsed.year_built and int(house["year_built"]) == int(parsed.year_built):
        score += 1.0
        reasons.append("gleiches Baujahr")
    similarity = _title_similarity(house.get("title"), parsed.title)
    if similarity >= 0.60:
        score += 1.0
        reasons.append(f"ähnlicher Titel {similarity:.2f}")
    return score, reasons


def _image_match_count(incoming: list[str], existing: list[str], max_distance: int = 6) -> int:
    matched_existing: set[int] = set()
    count = 0
    for new_hash in incoming:
        best_index = None
        best_distance = 999
        for index, old_hash in enumerate(existing):
            if index in matched_existing:
                continue
            distance = _hash_distance(new_hash, old_hash)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None and best_distance <= max_distance:
            matched_existing.add(best_index)
            count += 1
    return count


def find_existing_house_for_source(url: str, parsed: ParsedListing | None = None) -> dict[str, Any] | None:
    provider = parsed.source_name if parsed else provider_for_url(url)
    external_id = parsed.external_id if parsed else external_id_for_url(url)
    canonical = canonical_listing_url(parsed.source_url if parsed else url)
    with connect() as con:
        rows = con.execute(
            """
            SELECT h.*, s.source_name AS matched_source_name, s.source_url AS matched_source_url, s.external_id AS matched_external_id
            FROM houses h
            JOIN listing_sources s ON s.house_id = h.id
            ORDER BY h.created_at ASC
            """
        ).fetchall()
    for row in rows:
        data = row_to_dict(row) or {}
        if canonical_listing_url(str(data.get("matched_source_url") or "")) == canonical:
            return data
        if external_id and str(data.get("matched_external_id") or "") == str(external_id) and str(data.get("matched_source_name") or "") == provider:
            return data
    return None


async def find_probable_duplicate(parsed: ParsedListing) -> tuple[dict[str, Any] | None, str | None, float, dict[str, Any]]:
    incoming_hashes = await _remote_image_hashes(parsed.image_urls, 5) if parsed.image_urls else []
    best: tuple[dict[str, Any] | None, str | None, float, dict[str, Any]] = (None, None, 0.0, {})
    for house in list_houses():
        structured_score, reasons = _structured_match(house, parsed)
        existing_hashes = _local_media_hashes(str(house.get("id")), 12) if incoming_hashes else []
        image_matches = _image_match_count(incoming_hashes, existing_hashes)
        method: str | None = None
        confidence = structured_score
        if image_matches >= 2:
            method = "perceptual_images"
            confidence = 10.0 + image_matches
        elif image_matches >= 1 and structured_score >= 4.0:
            method = "image_plus_facts"
            confidence = 8.0 + structured_score
        elif structured_score >= 7.0:
            method = "structured_facts"
            confidence = structured_score
        elif "identische bestätigte Adresse" in reasons and structured_score >= 7.0:
            method = "exact_address"
            confidence = structured_score
        details = {"structured_score": structured_score, "reasons": reasons, "image_matches": image_matches}
        if method and confidence > best[2]:
            best = (house, method, confidence, details)
    return best


def _record_duplicate(house_id: str, parsed: ParsedListing, method: str, score: float, details: dict[str, Any]) -> None:
    with connect() as con:
        con.execute(
            """
            INSERT INTO duplicate_match_events (
                house_id, source_url, provider, external_id, match_method, match_score, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                house_id,
                parsed.source_url,
                parsed.source_name,
                parsed.external_id,
                method,
                score,
                json.dumps(details, ensure_ascii=False),
                now_iso(),
            ),
        )
        con.commit()


def _update_house_from_source(house_id: str, parsed: ParsedListing, *, same_source: bool) -> None:
    house = get_house(house_id) or {}
    fields: dict[str, Any] = {}
    if parsed.title and (not house.get("title") or str(house.get("title")).startswith("ImmobilienScout24 Exposé")):
        fields["title"] = parsed.title
    if parsed.location_text and (
        not house.get("location_text")
        or (parsed.address_status == "exact" and str(house.get("address_status") or "") != "exact")
    ):
        fields["location_text"] = parsed.location_text
        fields["address_status"] = parsed.address_status
    if parsed.price_eur is not None:
        current_price = house.get("price_eur")
        fields["price_eur"] = parsed.price_eur if same_source or current_price in (None, "") else min(int(current_price), int(parsed.price_eur))
    for field, value in {
        "living_area_m2": parsed.living_area_m2,
        "plot_area_m2": parsed.plot_area_m2,
        "rooms": parsed.rooms,
        "year_built": parsed.year_built,
        "heating": parsed.heating,
        "energy_hwb": parsed.energy_hwb,
        "energy_fgee": parsed.energy_fgee,
        "energy_class_hwb": parsed.energy_class_hwb,
        "energy_class_fgee": parsed.energy_class_fgee,
    }.items():
        if value is not None and house.get(field) in (None, ""):
            fields[field] = value
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sql = ", ".join(f"{key} = ?" for key in fields)
    with connect() as con:
        con.execute(f"UPDATE houses SET {sql} WHERE id = ?", list(fields.values()) + [house_id])
        con.commit()


def _safe_file_part(value: object, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]", "_", str(value or fallback))
    return (text or fallback)[:100]


def _store_or_refresh_source(house_id: str, parsed: ParsedListing, raw_html: str) -> tuple[dict[str, Any], bool]:
    canonical = canonical_listing_url(parsed.source_url)
    existing: dict[str, Any] | None = None
    for source in list_sources(house_id):
        if canonical_listing_url(str(source.get("source_url") or "")) == canonical:
            existing = source
            break
        if parsed.external_id and source.get("external_id") == parsed.external_id and source.get("source_name") == parsed.source_name:
            existing = source
            break
    html_name = f"listing_{_safe_file_part(parsed.source_name, 'portal')}_{_safe_file_part(parsed.external_id, hashlib.sha1(canonical.encode()).hexdigest()[:10])}.html"
    html_path = project_dir(house_id) / "html" / html_name
    html_path.write_text(raw_html, encoding="utf-8")
    warnings_json = json.dumps(parsed.warnings or [], ensure_ascii=False)
    if existing:
        with connect() as con:
            con.execute(
                """
                UPDATE listing_sources
                SET source_name = ?, source_url = ?, external_id = ?, description = ?, raw_html_path = ?,
                    parser_status = ?, parser_warnings = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    parsed.source_name,
                    canonical,
                    parsed.external_id,
                    parsed.description,
                    str(html_path),
                    "success" if not parsed.warnings else "partial",
                    warnings_json,
                    now_iso(),
                    existing["id"],
                ),
            )
            con.commit()
        existing.update({"source_url": canonical, "raw_html_path": str(html_path)})
        return existing, True
    source = create_source(
        house_id,
        {
            "source_name": parsed.source_name,
            "source_url": canonical,
            "external_id": parsed.external_id,
            "description": parsed.description,
            "raw_html_path": str(html_path),
            "parser_status": "success" if not parsed.warnings else "partial",
            "parser_warnings": parsed.warnings,
        },
    )
    return source, False


def _queue_media(house_id: str, source_id: str, parsed: ParsedListing) -> None:
    for image_url in parsed.image_urls:
        add_media(house_id, {"source_id": source_id, "kind": "image", "original_url": image_url, "download_status": "pending"})
    for pdf_url in parsed.pdf_urls:
        add_media(house_id, {"source_id": source_id, "kind": "pdf", "original_url": pdf_url, "download_status": "pending"})


def dedupe_house_images_perceptually(house_id: str) -> None:
    ensure_immoscout_schema()
    seen: list[tuple[str, str, int | None, int | None]] = []
    for media in sorted(list_media(house_id), key=lambda item: str(item.get("created_at") or "")):
        if media.get("kind") != "image" or media.get("download_status") != "downloaded" or not media.get("local_path"):
            continue
        path = Path(str(media.get("local_path")))
        try:
            path.resolve().relative_to(PROJECTS_DIR.resolve())
            content = path.read_bytes()
        except Exception:
            continue
        phash = _dhash(content)
        if not phash:
            continue
        width = int(media.get("width") or 0) or None
        height = int(media.get("height") or 0) or None
        duplicate_of = None
        for old_id, old_hash, old_width, old_height in seen:
            dimensions_close = True
            if width and height and old_width and old_height:
                ratio = (width / height) / (old_width / old_height)
                dimensions_close = 0.94 <= ratio <= 1.06
            if dimensions_close and _hash_distance(phash, old_hash) <= 2:
                duplicate_of = old_id
                break
        with connect() as con:
            if duplicate_of:
                con.execute(
                    "UPDATE media_assets SET perceptual_hash = ?, download_status = 'skipped', download_error = ? WHERE id = ?",
                    (phash, f"Visuelles Duplikat von Medium {duplicate_of}", media.get("id")),
                )
            else:
                con.execute("UPDATE media_assets SET perceptual_hash = ? WHERE id = ?", (phash, media.get("id")))
            con.commit()
        if not duplicate_of:
            seen.append((str(media.get("id")), phash, width, height))


async def download_pending_media_enhanced(house_id: str, limit: int = 120) -> None:
    if not _ORIGINAL_DOWNLOAD_MEDIA:
        return
    await _ORIGINAL_DOWNLOAD_MEDIA(house_id, limit)
    dedupe_house_images_perceptually(house_id)


async def import_listing_to_pipeline_multi(url: str, preview_image_url: str | None = None) -> dict[str, Any]:
    import app.github_auto_export as github_auto_export
    import app.gmail_exchange as gmail_exchange
    import app.house_manage as house_manage
    import app.pipeline_status as pipeline_status

    if not str(url or "").startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Ungültige URL")
    if provider_for_url(url) not in {WILLHABEN_SOURCE, IMMOSCOUT_SOURCE}:
        raise HTTPException(status_code=400, detail="Unterstützt werden Willhaben und ImmobilienScout24 Österreich")

    import app.main as main_module

    raw_html = await main_module.fetch_html(url)
    parsed = parse_listing_multi(url, raw_html)
    existing = find_existing_house_for_source(url, parsed)
    duplicate_method = "same_source" if existing else None
    duplicate_score = 100.0 if existing else 0.0
    duplicate_details: dict[str, Any] = {}
    if not existing:
        existing, duplicate_method, duplicate_score, duplicate_details = await find_probable_duplicate(parsed)

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
        pipeline_status.set_pipeline_stage(str(house["id"]), "created", "ok", "Hausakte wurde angelegt.")
    else:
        house = existing or {}
        _record_duplicate(str(house["id"]), parsed, duplicate_method or "duplicate", duplicate_score, duplicate_details)
        pipeline_status.set_pipeline_stage(
            str(house["id"]),
            "source_merged",
            "ok",
            "Inserat wurde als weitere Quelle einer vorhandenen Hausakte zugeordnet.",
        )

    house_id = str(house["id"])
    house_manage.set_house_preview(house_id, preview_image_url or (parsed.image_urls[0] if parsed.image_urls else None))
    source, same_source = _store_or_refresh_source(house_id, parsed, raw_html)
    _update_house_from_source(house_id, parsed, same_source=same_source)
    add_evidence(house_id, str(source.get("id") or ""), parsed.evidence)
    if not created:
        add_evidence(
            house_id,
            str(source.get("id") or ""),
            [
                {
                    "field_name": "duplicate_match",
                    "value": duplicate_method or "duplicate",
                    "source_label": "Automatische Duplikaterkennung",
                    "source_text_snippet": json.dumps(duplicate_details, ensure_ascii=False)[:300],
                    "confidence": "verified" if duplicate_method in {"same_source", "perceptual_images", "exact_address"} else "derived",
                }
            ],
        )
    mark_candidates_imported(parsed.source_url, house_id)
    _queue_media(house_id, str(source.get("id") or ""), parsed)
    pipeline_status.set_pipeline_stage(house_id, "media_loading", "running", "Inseratbilder und Dokumente werden geladen.")
    await download_pending_media_enhanced(house_id)
    media = list_media(house_id)
    downloaded = len([item for item in media if item.get("download_status") == "downloaded"])
    failed = len([item for item in media if item.get("download_status") == "failed"])
    pipeline_status.set_pipeline_stage(
        house_id,
        "media_ready",
        "ok" if downloaded else "error",
        f"Medienabruf abgeschlossen: {downloaded} geladen, {failed} fehlgeschlagen.",
        error=None if downloaded else "Keine Medien konnten geladen werden.",
    )
    await github_auto_export.auto_export_house_to_github(house_id)
    await gmail_exchange.send_analysis_zip_via_gmail(house_id)
    return {
        "house": get_house(house_id) or house,
        "created": created,
        "duplicate": not created,
        "duplicate_method": duplicate_method,
    }


def sync_candidate_metadata_multi(profile_id: str) -> None:
    import app.search_automation as search_automation
    from app.storage import list_search_candidates

    if _ORIGINAL_SYNC_CANDIDATES:
        _ORIGINAL_SYNC_CANDIDATES(profile_id)
    with connect() as con:
        for candidate in list_search_candidates(profile_id):
            source_url = str(candidate.get("source_url") or "")
            con.execute(
                """
                UPDATE search_candidates
                SET provider = ?, external_id = ?, canonical_url = ?
                WHERE id = ?
                """,
                (
                    provider_for_url(source_url),
                    external_id_for_url(source_url),
                    canonical_listing_url(source_url),
                    candidate.get("id"),
                ),
            )
        con.commit()


def _profile_form_html() -> str:
    return """
    <div class="card">
      <h2>Neues Suchprofil</h2>
      <form method="post" action="profiles" data-loading="Immobilienportale werden gespeichert …">
        <label>Name</label><input name="name" placeholder="Familienhaus Südweststeiermark" required>
        <label>Portal</label>
        <select name="source_name">
          <option value="willhaben.at">Willhaben</option>
          <option value="immobilienscout24.at">ImmobilienScout24 Österreich</option>
        </select>
        <label>Regionen / Orte</label><input name="regions" value="Wies, Eibiswald, Oberhaag, Gleinstätten, Bad Schwanberg, Pölfing-Brunn, Frauental, Deutschlandsberg">
        <label>Suchergebnis-URL</label>
        <input name="search_url" placeholder="ImmobilienScout: vollständige /regional/... URL; Willhaben optional">
        <p class="muted">Bei ImmobilienScout24 die fertige Such-URL aus dem Browser einfügen. Bei Willhaben kann das Feld leer bleiben.</p>
        <label>Willhaben PLZ / areaIds</label><input name="area_ids" value="8551,8552,8544,8553">
        <div class="grid">
          <div><label>Zielpreis bis €</label><input name="soft_max_price_eur" type="number" value="380000"></div>
          <div><label>Harte Grenze bis €</label><input name="max_price_eur" type="number" value="420000"></div>
          <div><label>Mindestwohnfläche m²</label><input name="min_living_area_m2" type="number" step="0.1" value="120"></div>
          <div><label>Wunsch-Grundstück m²</label><input name="min_plot_area_m2" type="number" step="0.1" value="700"></div>
          <div><label>HWB Warnung ab</label><input name="hwb_warn" type="number" step="0.1" value="200"></div>
          <div><label>HWB kritisch ab</label><input name="hwb_reject" type="number" step="0.1" value="300"></div>
        </div>
        <label>Ausschluss-/Prüfbegriffe</label><input name="exclude_roads" value="B76,B69,Bundesstraße,Hauptstraße">
        <div class="grid">
          <div><label>Ölheizung</label><select name="oil_policy"><option value="review" selected>prüfen</option><option value="reject">ausschließen</option><option value="allow">zulassen</option></select></div>
          <div><label>Modus</label><select name="automation_mode"><option value="manual">nur manuell</option><option value="review" selected>automatisch suchen, manuell importieren</option><option value="automatic">automatisch suchen und importieren</option></select></div>
          <div><label>Intervall Minuten</label><input name="run_interval_minutes" type="number" value="60" min="15"></div>
          <div><label>Max. Treffer</label><input name="max_results" type="number" value="80" min="10" max="160"></div>
          <div><label>Auto-Import ab Score</label><input name="auto_import_min_score" type="number" value="68" min="0" max="100"></div>
          <div><label>Max. Auto-Importe</label><input name="auto_import_limit_per_run" type="number" value="2" min="1" max="10"></div>
        </div>
        <button type="submit">Suchprofil speichern</button>
      </form>
    </div>
    """


def _profile_card_multi(profile: dict[str, Any]) -> str:
    if not _ORIGINAL_PROFILE_CARD:
        return ""
    html = _ORIGINAL_PROFILE_CARD(profile)
    provider = str(profile.get("source_name") or WILLHABEN_SOURCE)
    label = "ImmobilienScout24" if provider == IMMOSCOUT_SOURCE else "Willhaben"
    urls = [item.strip() for item in re.split(r"[\n;]+", str(profile.get("search_url") or "")) if item.strip()]
    summary = f'<p class="muted"><strong>Portal:</strong> {label}'
    if urls:
        summary += f'<br><span style="overflow-wrap:anywhere">{html_lib.escape(urls[0])}</span>'
    summary += "</p>"
    return html.replace("<p>", summary + "<p>", 1)


def _as_int(value: str | None) -> int | None:
    try:
        return int(float(str(value))) if str(value or "").strip() else None
    except Exception:
        return None


def _as_float(value: str | None) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if str(value or "").strip() else None
    except Exception:
        return None


def _validate_search_profile_url(source_name: str, search_url: str, profile_data: dict[str, Any], area_ids: str | None) -> tuple[str, str]:
    import app.main as main_module

    raw_url = str(search_url or "").strip()
    provider = source_name if source_name in {WILLHABEN_SOURCE, IMMOSCOUT_SOURCE} else WILLHABEN_SOURCE
    if raw_url:
        if not raw_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Ungültige Such-URL")
        detected = provider_for_url(raw_url)
        if detected not in {WILLHABEN_SOURCE, IMMOSCOUT_SOURCE}:
            raise HTTPException(status_code=400, detail="Unterstützt werden Willhaben und ImmobilienScout24 Österreich")
        provider = detected
        return provider, raw_url
    if provider == IMMOSCOUT_SOURCE:
        raise HTTPException(status_code=400, detail="Für ImmobilienScout24 muss eine vollständige Suchergebnis-URL angegeben werden")
    return WILLHABEN_SOURCE, "\n".join(main_module.build_willhaben_auto_urls(profile_data, area_ids))


def _create_profile_data(
    *,
    name: str,
    source_name: str,
    search_url: str | None,
    area_ids: str | None,
    regions: str | None,
    max_price_eur: str | None,
    soft_max_price_eur: str | None,
    min_living_area_m2: str | None,
    min_plot_area_m2: str | None,
    exclude_roads: str | None,
    hwb_warn: str | None,
    hwb_reject: str | None,
    oil_policy: str | None,
) -> dict[str, Any]:
    profile_data: dict[str, Any] = {
        "name": name.strip(),
        "source_name": source_name,
        "max_price_eur": _as_int(max_price_eur),
        "soft_max_price_eur": _as_int(soft_max_price_eur),
        "min_living_area_m2": _as_float(min_living_area_m2),
        "min_plot_area_m2": _as_float(min_plot_area_m2),
        "regions": str(regions or "").strip(),
        "exclude_roads": exclude_roads,
        "hwb_warn": _as_float(hwb_warn),
        "hwb_reject": _as_float(hwb_reject),
        "oil_policy": oil_policy or "review",
    }
    provider, resolved_url = _validate_search_profile_url(source_name, str(search_url or ""), profile_data, area_ids)
    profile_data["source_name"] = provider
    profile_data["search_url"] = resolved_url
    return profile_data


def _register_profile_routes(app: FastAPI) -> None:
    import app.search_automation as search_automation

    _remove_route(app, "/settings/search/profiles", "POST")
    _remove_route(app, "/search/profiles", "POST")

    async def create_common(
        name: str,
        source_name: str,
        search_url: str | None,
        area_ids: str | None,
        regions: str | None,
        max_price_eur: str | None,
        soft_max_price_eur: str | None,
        min_living_area_m2: str | None,
        min_plot_area_m2: str | None,
        exclude_roads: str | None,
        hwb_warn: str | None,
        hwb_reject: str | None,
        oil_policy: str | None,
        automation_mode: str | None,
        run_interval_minutes: int,
        max_results: int,
        auto_import_min_score: int,
        auto_import_limit_per_run: int,
    ) -> dict[str, Any]:
        profile_data = _create_profile_data(
            name=name,
            source_name=source_name,
            search_url=search_url,
            area_ids=area_ids,
            regions=regions,
            max_price_eur=max_price_eur,
            soft_max_price_eur=soft_max_price_eur,
            min_living_area_m2=min_living_area_m2,
            min_plot_area_m2=min_plot_area_m2,
            exclude_roads=exclude_roads,
            hwb_warn=hwb_warn,
            hwb_reject=hwb_reject,
            oil_policy=oil_policy,
        )
        profile = create_search_profile(profile_data)
        mode = automation_mode if automation_mode in {"manual", "review", "automatic"} else "review"
        search_automation.update_profile_automation(
            str(profile["id"]),
            {
                "enabled": 1,
                "area_ids": str(area_ids or "").strip(),
                "automation_mode": mode,
                "run_interval_minutes": max(15, min(int(run_interval_minutes or 60), 1440)),
                "auto_import_enabled": 1 if mode == "automatic" else 0,
                "max_results": max(10, min(int(max_results or 80), 160)),
                "auto_import_min_score": max(0, min(int(auto_import_min_score or 68), 100)),
                "auto_import_limit_per_run": max(1, min(int(auto_import_limit_per_run or 2), 10)),
                "last_run_status": "bereit",
            },
        )
        return profile

    @app.post("/settings/search/profiles")
    async def create_profile_settings(
        name: str = Form(...),
        source_name: str = Form(WILLHABEN_SOURCE),
        search_url: str | None = Form(None),
        area_ids: str | None = Form("8551"),
        regions: str | None = Form(None),
        max_price_eur: str | None = Form(None),
        soft_max_price_eur: str | None = Form(None),
        min_living_area_m2: str | None = Form(None),
        min_plot_area_m2: str | None = Form(None),
        exclude_roads: str | None = Form(None),
        hwb_warn: str | None = Form(None),
        hwb_reject: str | None = Form(None),
        oil_policy: str | None = Form("review"),
        automation_mode: str | None = Form("review"),
        run_interval_minutes: int = Form(60),
        max_results: int = Form(80),
        auto_import_min_score: int = Form(68),
        auto_import_limit_per_run: int = Form(2),
    ) -> RedirectResponse:
        await create_common(
            name, source_name, search_url, area_ids, regions, max_price_eur, soft_max_price_eur,
            min_living_area_m2, min_plot_area_m2, exclude_roads, hwb_warn, hwb_reject,
            oil_policy, automation_mode, run_interval_minutes, max_results,
            auto_import_min_score, auto_import_limit_per_run,
        )
        return RedirectResponse("../search", status_code=303)

    @app.post("/search/profiles")
    async def create_profile_legacy(
        name: str = Form(...),
        source_name: str = Form(WILLHABEN_SOURCE),
        search_url: str | None = Form(None),
        area_ids: str | None = Form("8551"),
        regions: str | None = Form(None),
        max_price_eur: str | None = Form(None),
        soft_max_price_eur: str | None = Form(None),
        min_living_area_m2: str | None = Form(None),
        min_plot_area_m2: str | None = Form(None),
        exclude_roads: str | None = Form(None),
        hwb_warn: str | None = Form(None),
        hwb_reject: str | None = Form(None),
        oil_policy: str | None = Form("review"),
        automation_mode: str | None = Form("review"),
        run_interval_minutes: int = Form(60),
        max_results: int = Form(80),
        auto_import_min_score: int = Form(68),
        auto_import_limit_per_run: int = Form(2),
    ) -> RedirectResponse:
        profile = await create_common(
            name, source_name, search_url, area_ids, regions, max_price_eur, soft_max_price_eur,
            min_living_area_m2, min_plot_area_m2, exclude_roads, hwb_warn, hwb_reject,
            oil_policy, automation_mode, run_interval_minutes, max_results,
            auto_import_min_score, auto_import_limit_per_run,
        )
        return RedirectResponse(f"profiles/{profile['id']}", status_code=303)


def register_immoscout_support(app: FastAPI) -> None:
    global _PATCHED
    global _ORIGINAL_PARSE_LISTING, _ORIGINAL_EXTRACT_CANDIDATES, _ORIGINAL_TITLE_FROM_URL
    global _ORIGINAL_DOWNLOAD_MEDIA, _ORIGINAL_SYNC_CANDIDATES, _ORIGINAL_PROFILE_CARD
    if _PATCHED:
        return

    import app.focused_ui as focused_ui
    import app.import_patch as import_patch
    import app.main as main_module
    import app.search_automation as search_automation
    import app.search_lifecycle_ui as lifecycle_ui
    import app.search_ui_patch as search_ui_patch
    import app.storage as storage_module

    ensure_immoscout_schema()
    _ORIGINAL_PARSE_LISTING = parser_module.parse_listing
    _ORIGINAL_EXTRACT_CANDIDATES = parser_module.extract_listing_candidates
    _ORIGINAL_TITLE_FROM_URL = parser_module.title_from_listing_url
    _ORIGINAL_DOWNLOAD_MEDIA = main_module.download_pending_media_files
    _ORIGINAL_SYNC_CANDIDATES = search_automation.sync_candidate_metadata
    _ORIGINAL_PROFILE_CARD = lifecycle_ui._profile_card

    parser_module.parse_listing = parse_listing_multi
    parser_module.extract_listing_candidates = extract_listing_candidates_multi
    parser_module.extract_listing_links = extract_listing_links_multi
    parser_module.title_from_listing_url = title_from_listing_url_multi

    main_module.parse_listing = parse_listing_multi
    main_module.extract_listing_links = extract_listing_links_multi
    main_module.title_from_listing_url = title_from_listing_url_multi
    main_module.listing_key = listing_key_multi
    main_module.source_url_exists = source_url_exists_multi
    main_module.download_pending_media_files = download_pending_media_enhanced

    storage_module.source_url_exists = source_url_exists_multi
    import_patch.find_existing_house_for_url = find_existing_house_for_source
    import_patch.import_listing_to_pipeline = import_listing_to_pipeline_multi
    import_patch.parse_listing = parse_listing_multi
    import_patch.download_pending_media_files = download_pending_media_enhanced

    search_automation.run_search_profile = main_module.run_search_profile
    search_automation.source_url_exists = source_url_exists_multi
    search_automation.import_listing_to_pipeline = import_listing_to_pipeline_multi
    search_automation._external_id = external_id_for_url
    search_automation._canonical_url = canonical_listing_url
    search_automation.sync_candidate_metadata = sync_candidate_metadata_multi

    search_ui_patch.source_url_exists = source_url_exists_multi
    search_ui_patch.title_from_listing_url = title_from_listing_url_multi
    focused_ui.title_from_listing_url = title_from_listing_url_multi
    lifecycle_ui.title_from_listing_url = title_from_listing_url_multi
    lifecycle_ui._new_profile_form = _profile_form_html
    lifecycle_ui._profile_card = _profile_card_multi

    _register_profile_routes(app)
    _PATCHED = True
