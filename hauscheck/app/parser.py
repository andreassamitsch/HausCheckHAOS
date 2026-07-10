from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup


@dataclass
class ParsedListing:
    source_name: str
    source_url: str
    external_id: str | None = None
    title: str = "Unbenanntes Objekt"
    description: str | None = None
    price_eur: int | None = None
    living_area_m2: float | None = None
    plot_area_m2: float | None = None
    rooms: float | None = None
    location_text: str | None = None
    address_status: str = "unknown"
    year_built: int | None = None
    heating: str | None = None
    energy_hwb: float | None = None
    energy_fgee: float | None = None
    energy_class_hwb: str | None = None
    energy_class_fgee: str | None = None
    image_urls: list[str] = field(default_factory=list)
    pdf_urls: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SearchResultCandidate:
    url: str
    title: str | None = None
    preview_image_url: str | None = None


BAD_IMAGE_MARKERS = (
    "logo", "avatar", "profile", "profil", "company", "makler", "agent",
    "favicon", "sprite", "icon", "placeholder", "banner", "tracking",
)


def parse_number(value: str) -> float | None:
    cleaned = value.strip().replace("\u00a0", " ")
    cleaned = cleaned.replace(".", "").replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_int_eur(text: str) -> int | None:
    patterns = [
        r"(?:€|EUR)\s*([0-9][0-9\.\s]*)(?:,-)?",
        r"Kaufpreis\s*(?:€|EUR)?\s*([0-9][0-9\.\s]*)",
        r"([0-9][0-9\.\s]*)\s*(?:€|EUR)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            number = parse_number(match.group(1))
            if number:
                return int(number)
    return None


def first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            value = node.get_text(" ", strip=True)
            if value:
                return value
    return None


def add_evidence(result: ParsedListing, field_name: str, value: Any, label: str, snippet: str | None, confidence: str) -> None:
    result.evidence.append(
        {
            "field_name": field_name,
            "value": value,
            "source_label": label,
            "source_text_snippet": snippet[:300] if snippet else None,
            "confidence": confidence,
        }
    )


def extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            objects.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            objects.append(data)
    return objects


def normalize_url(url: str) -> str:
    url = html_lib.unescape(url).replace("\\/", "/").strip()
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def normalize_image_url(url: str) -> str:
    return normalize_url(url)


def looks_like_logo_or_ui_asset(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in BAD_IMAGE_MARKERS)


def image_patterns(willhaben_gallery_only: bool = False) -> list[str]:
    if willhaben_gallery_only:
        return [r"https://cache\.willhaben\.at/mmo/[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)"]
    return [
        r"https://cache\.willhaben\.at/mmo/[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)",
        r"https://[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)",
    ]


def extract_image_urls_ordered(raw_html: str, *, willhaben_gallery_only: bool = False) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for pattern in image_patterns(willhaben_gallery_only):
        for match in re.finditer(pattern, raw_html, re.IGNORECASE):
            url = normalize_image_url(match.group(0))
            if not url or looks_like_logo_or_ui_asset(url) or url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def extract_image_urls(raw_html: str, *, willhaben_gallery_only: bool = False) -> list[str]:
    return sorted(extract_image_urls_ordered(raw_html, willhaben_gallery_only=willhaben_gallery_only))


def extract_pdf_urls(raw_html: str) -> list[str]:
    urls = set()
    for match in re.finditer(r"https://[^\"'\\\s<>]+?\.pdf", raw_html, re.IGNORECASE):
        urls.add(html_lib.unescape(match.group(0)).replace("\\/", "/"))
    return sorted(urls)


def is_detail_listing_link(candidate: str) -> bool:
    if "/iad/immobilien/d/" not in candidate:
        return False
    return bool(re.search(r"-\d{7,}(?:$|[/?#])", candidate))


def extract_listing_candidates(raw_html: str, base_url: str) -> list[SearchResultCandidate]:
    """Extract portal result cards from a search page.

    For Willhaben this tries to use the same thumbnail image that is present in
    the overview result card. If no card image is found, the candidate is still
    returned without a preview so the detail page can be parsed later.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    by_url: dict[str, SearchResultCandidate] = {}

    def add_candidate(raw_href: str, title: str | None = None, preview: str | None = None) -> None:
        raw_href = html_lib.unescape(raw_href).replace("\\/", "/")
        if not is_detail_listing_link(raw_href):
            return
        absolute = urljoin(base_url, raw_href)
        normalized = normalize_url(absolute)
        current = by_url.get(normalized)
        if current is None:
            by_url[normalized] = SearchResultCandidate(url=normalized, title=title, preview_image_url=preview)
            return
        if title and not current.title:
            current.title = title
        if preview and not current.preview_image_url:
            current.preview_image_url = preview

    for tag in soup.find_all("a", href=True):
        href = str(tag.get("href") or "")
        if not is_detail_listing_link(href):
            continue
        title = tag.get_text(" ", strip=True) or None
        card_html = ""
        node = tag
        for _ in range(7):
            if node is None:
                break
            node_html = str(node)
            if "cache.willhaben.at/mmo/" in node_html:
                card_html = node_html
                break
            parent = getattr(node, "parent", None)
            if parent is None or getattr(parent, "name", None) in ("body", "html"):
                break
            node = parent
        preview = None
        if card_html:
            images = extract_image_urls_ordered(card_html, willhaben_gallery_only=True)
            if not images:
                images = extract_image_urls_ordered(card_html, willhaben_gallery_only=False)
            preview = images[0] if images else None
        add_candidate(href, title=title, preview=preview)

    regexes = [
        r"https://www\.willhaben\.at/iad/immobilien/d/[^\"'\\\s<>]+?-\d{7,}",
        r"/iad/immobilien/d/[^\"'\\\s<>]+?-\d{7,}",
    ]
    for regex in regexes:
        for match in re.finditer(regex, raw_html, re.IGNORECASE):
            add_candidate(match.group(0))

    return list(by_url.values())


def extract_listing_links(raw_html: str, base_url: str) -> list[str]:
    """Extract real detail listing links from a portal/search HTML page."""
    return sorted(candidate.url for candidate in extract_listing_candidates(raw_html, base_url))


def title_from_listing_url(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    slug = path.split("/")[-1]
    slug = re.sub(r"-\d{7,}$", "", slug)
    slug = slug.replace("-", " ").strip()
    return slug[:1].upper() + slug[1:] if slug else url


def parse_willhaben_id(url: str) -> str | None:
    match = re.search(r"-(\d{7,})/?(?:$|[?#])", url)
    return match.group(1) if match else None


def parse_willhaben(url: str, raw_html: str) -> ParsedListing:
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    result = ParsedListing(source_name="willhaben.at", source_url=url, external_id=parse_willhaben_id(url))

    title = None
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = str(og_title.get("content"))
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    if title:
        result.title = title.split(" | ")[0].strip()
        add_evidence(result, "title", result.title, "og:title/title", title, "verified")

    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        result.description = str(og_desc.get("content")).strip()
        add_evidence(result, "description", result.description, "og:description", result.description, "derived")

    result.price_eur = parse_int_eur(text)
    if result.price_eur:
        add_evidence(result, "price_eur", result.price_eur, "text/price", "Kaufpreis/€ im Seitentext", "derived")

    living_patterns = [
        r"Wohnfläche\s*([0-9][0-9\.,\s]*)\s*m",
        r"Wohnnutzfläche\s*([0-9][0-9\.,\s]*)\s*m",
    ]
    for pattern in living_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result.living_area_m2 = parse_number(match.group(1))
            add_evidence(result, "living_area_m2", result.living_area_m2, "explicit living area label", match.group(0), "verified")
            break

    plot_patterns = [
        r"Grundstücksfläche\s*([0-9][0-9\.,\s]*)\s*m",
        r"Grundfläche\s*([0-9][0-9\.,\s]*)\s*m",
        r"Grundstück\s*([0-9][0-9\.,\s]*)\s*m",
    ]
    for pattern in plot_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result.plot_area_m2 = parse_number(match.group(1))
            add_evidence(result, "plot_area_m2", result.plot_area_m2, "explicit plot area label", match.group(0), "verified")
            break

    if result.plot_area_m2 is None:
        result.warnings.append("Grundstücksfläche nicht sicher erkannt")

    room_match = re.search(r"Zimmer\s*([0-9][0-9\.,]*)", text, re.IGNORECASE)
    if room_match:
        result.rooms = parse_number(room_match.group(1))
        add_evidence(result, "rooms", result.rooms, "Zimmer label", room_match.group(0), "derived")

    year_match = re.search(r"Baujahr\s*([12][0-9]{3})", text, re.IGNORECASE)
    if year_match:
        result.year_built = int(year_match.group(1))
        add_evidence(result, "year_built", result.year_built, "Baujahr label", year_match.group(0), "verified")

    heating_match = re.search(r"(?:Heizung|Heizungsart)\s*([A-Za-zÄÖÜäöüß /\-]+?)(?:\s{2,}|HWB|fGEE|Energie|Baujahr|Zimmer|$)", text, re.IGNORECASE)
    if heating_match:
        result.heating = heating_match.group(1).strip()[:120]
        add_evidence(result, "heating", result.heating, "Heizung label", heating_match.group(0), "derived")

    hwb_match = re.search(r"HWB[^0-9]{0,40}([0-9]+(?:[\.,][0-9]+)?)", text, re.IGNORECASE)
    if hwb_match:
        result.energy_hwb = parse_number(hwb_match.group(1))
        add_evidence(result, "energy_hwb", result.energy_hwb, "HWB label", hwb_match.group(0), "verified")
        if result.energy_hwb and result.energy_hwb > 200:
            result.warnings.append(f"Kritischer HWB-Wert: {result.energy_hwb:g}")

    fgee_match = re.search(r"f\s*\{?GEE\}?[^0-9]{0,40}([0-9]+(?:[\.,][0-9]+)?)", text, re.IGNORECASE)
    if fgee_match:
        result.energy_fgee = parse_number(fgee_match.group(1))
        add_evidence(result, "energy_fgee", result.energy_fgee, "fGEE label", fgee_match.group(0), "verified")

    for obj in extract_json_ld(soup):
        address = obj.get("address")
        if isinstance(address, dict):
            parts = [address.get("streetAddress"), address.get("postalCode"), address.get("addressLocality")]
            location = ", ".join(str(p) for p in parts if p)
            if location:
                result.location_text = location
                result.address_status = "exact" if address.get("streetAddress") else "municipality_only"
                add_evidence(result, "location_text", result.location_text, "JSON-LD address", location, "verified")
                break

    if result.location_text is None:
        loc_match = re.search(r"([0-9]{4}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\- ]{2,60})", text)
        if loc_match:
            result.location_text = loc_match.group(1).strip()
            result.address_status = "municipality_only"
            add_evidence(result, "location_text", result.location_text, "postal code text", loc_match.group(0), "derived")

    result.image_urls = extract_image_urls(raw_html, willhaben_gallery_only=True)
    if not result.image_urls:
        result.image_urls = extract_image_urls(raw_html, willhaben_gallery_only=False)
        result.warnings.append("Keine eindeutigen Willhaben-Galerie-URLs erkannt; generische Bildsuche verwendet")

    result.pdf_urls = extract_pdf_urls(raw_html)
    if not result.image_urls:
        result.warnings.append("Keine Bild-URLs im HTML erkannt")

    return result


def parse_listing(url: str, raw_html: str) -> ParsedListing:
    host = urlparse(url).netloc.lower()
    if "willhaben.at" in host:
        return parse_willhaben(url, raw_html)
    result = ParsedListing(source_name=host or "unknown", source_url=url)
    soup = BeautifulSoup(raw_html, "html.parser")
    if soup.title:
        result.title = soup.title.get_text(" ", strip=True)
    result.description = first_text(soup, ["meta[name=description]"])
    result.image_urls = extract_image_urls(raw_html)
    result.pdf_urls = extract_pdf_urls(raw_html)
    result.warnings.append("Portal noch nicht spezifisch implementiert; generischer Import")
    return result
