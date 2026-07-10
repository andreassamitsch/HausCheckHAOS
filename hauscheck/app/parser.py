from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

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


def extract_image_urls(html: str) -> list[str]:
    urls = set()
    patterns = [
        r"https://cache\.willhaben\.at/mmo/[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)",
        r"https://[^\"'\\\s<>]+?\.(?:jpg|jpeg|png|webp)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            url = match.group(0).replace("\\/", "/")
            urls.add(url)
    return sorted(urls)


def extract_pdf_urls(html: str) -> list[str]:
    urls = set()
    for match in re.finditer(r"https://[^\"'\\\s<>]+?\.pdf", html, re.IGNORECASE):
        urls.add(match.group(0).replace("\\/", "/"))
    return sorted(urls)


def parse_willhaben_id(url: str) -> str | None:
    match = re.search(r"-(\d{7,})/?(?:$|[?#])", url)
    return match.group(1) if match else None


def parse_willhaben(url: str, html: str) -> ParsedListing:
    soup = BeautifulSoup(html, "html.parser")
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

    # Strict field parsing: only explicit labels may populate area fields.
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

    # Address/location via JSON-LD if available.
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

    result.image_urls = extract_image_urls(html)
    result.pdf_urls = extract_pdf_urls(html)
    if not result.image_urls:
        result.warnings.append("Keine Bild-URLs im HTML erkannt")

    return result


def parse_listing(url: str, html: str) -> ParsedListing:
    host = urlparse(url).netloc.lower()
    if "willhaben.at" in host:
        return parse_willhaben(url, html)
    result = ParsedListing(source_name=host or "unknown", source_url=url)
    soup = BeautifulSoup(html, "html.parser")
    if soup.title:
        result.title = soup.title.get_text(" ", strip=True)
    result.description = first_text(soup, ["meta[name=description]"])
    result.image_urls = extract_image_urls(html)
    result.pdf_urls = extract_pdf_urls(html)
    result.warnings.append("Portal noch nicht spezifisch implementiert; generischer Import")
    return result
