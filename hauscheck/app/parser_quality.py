from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import app.house_manage as house_manage
import app.import_patch as import_patch
import app.main as main
import app.parser as parser


_patched = False


def parse_energy_number(value: object) -> float | None:
    """Parse energy values with Austrian/German decimal conventions.

    For HWB/fGEE a single dot is treated as a decimal separator as requested,
    not as a thousands separator. If both separators are present, the last one
    is considered the decimal separator.
    """
    text = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    match = re.search(r"[0-9]+(?:[\.,][0-9]+)*", text)
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." in token:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        token = token.replace(thousands, "").replace(decimal, ".")
    elif "," in token:
        token = token.replace(".", "").replace(",", ".")
    # Eine alleinstehende Periode bleibt bewusst Dezimaltrennzeichen.
    try:
        return float(token)
    except ValueError:
        return None


def parse_local_decimal(value: object) -> float | None:
    """Parse user-entered decimal values without turning 306.1 into 3061."""
    text = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+", text):
        # Bei allgemeinen Flächenwerten bleibt die übliche Tausendernotation möglich.
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _value_after_label(text: str, label_pattern: str) -> tuple[str, float] | None:
    match = re.search(
        rf"(?:{label_pattern})[^0-9]{{0,60}}([0-9]+(?:[\.,][0-9]+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    raw = match.group(1)
    value = parse_energy_number(raw)
    return (raw, value) if value is not None else None


def _structured_energy_value(
    soup: BeautifulSoup,
    label_pattern: str,
) -> tuple[float, str, str] | None:
    candidates: list[tuple[int, int, float, str, str]] = []
    order = 0

    def add_candidate(priority: int, text: str, source: str) -> None:
        nonlocal order
        order += 1
        compact = " ".join(str(text or "").split())
        if not compact or len(compact) > 450:
            return
        found = _value_after_label(compact, label_pattern)
        if not found:
            return
        raw, value = found
        decimal_bonus = 4 if "," in raw else 2 if "." in raw else 0
        candidates.append((priority + decimal_bonus, -order, value, compact[:300], source))

    # Explizite Werttabellen und Definitionslisten haben immer Vorrang.
    for row in soup.find_all("tr"):
        add_candidate(120, row.get_text(" ", strip=True), "Werttabelle")

    for dt in soup.find_all("dt"):
        label_text = dt.get_text(" ", strip=True)
        if not re.search(label_pattern, label_text, re.IGNORECASE):
            continue
        dd = dt.find_next_sibling("dd")
        if dd:
            add_candidate(120, f"{label_text} {dd.get_text(' ', strip=True)}", "Definitionsliste")

    for row in soup.select('[role="row"]'):
        add_candidate(115, row.get_text(" ", strip=True), "Werteliste")

    for item in soup.find_all("li"):
        add_candidate(105, item.get_text(" ", strip=True), "Werteliste")

    # Willhaben und andere Portale verwenden häufig kurze DIV-Zeilen statt echter Tabellen.
    for node in soup.find_all(["div", "section", "p"]):
        direct = " ".join(node.stripped_strings)
        if re.search(label_pattern, direct, re.IGNORECASE):
            add_candidate(80, direct, "strukturierter Werteblock")

    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, _, value, snippet, source = candidates[0]
    return value, snippet, source


def _replace_energy_evidence(
    result: parser.ParsedListing,
    field_name: str,
    value: float | None,
    label: str,
    snippet: str,
    confidence: str,
) -> None:
    result.evidence = [item for item in result.evidence if item.get("field_name") != field_name]
    if value is not None:
        parser.add_evidence(result, field_name, value, label, snippet, confidence)


def _correct_willhaben_energy(
    result: parser.ParsedListing,
    raw_html: str,
) -> parser.ParsedListing:
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(" ", strip=True)

    structured_hwb = _structured_energy_value(soup, r"HWB(?:\s*[-–]?\s*Wert)?")
    if structured_hwb:
        hwb, snippet, source = structured_hwb
        result.energy_hwb = hwb
        _replace_energy_evidence(result, "energy_hwb", hwb, f"HWB aus {source}", snippet, "verified")
    else:
        found = _value_after_label(text, r"HWB(?:\s*[-–]?\s*Wert)?")
        if found:
            _, hwb = found
            result.energy_hwb = hwb
            _replace_energy_evidence(result, "energy_hwb", hwb, "HWB Dezimalwert", "HWB im Seitentext", "derived")

    structured_fgee = _structured_energy_value(soup, r"f\s*\{?GEE\}?")
    if structured_fgee:
        fgee, snippet, source = structured_fgee
        result.energy_fgee = fgee
        _replace_energy_evidence(result, "energy_fgee", fgee, f"fGEE aus {source}", snippet, "verified")
    else:
        found = _value_after_label(text, r"f\s*\{?GEE\}?")
        if found:
            _, fgee = found
            result.energy_fgee = fgee
            _replace_energy_evidence(result, "energy_fgee", fgee, "fGEE Dezimalwert", "fGEE im Seitentext", "derived")

    result.warnings = [warning for warning in result.warnings if not warning.startswith("Kritischer HWB-Wert:")]
    if result.energy_hwb is not None and result.energy_hwb > 200:
        result.warnings.append(f"Kritischer HWB-Wert: {result.energy_hwb:g}")
    return result


def _correct_pdf_energy(
    original: Callable[[str], tuple[dict[str, Any], list[dict[str, Any]]]],
    text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    facts, evidence = original(text)
    replacements = {
        "energy_hwb": (r"HWB(?:\s*[-–]?\s*Wert)?", "Exposé PDF HWB Dezimalwert"),
        "energy_fgee": (r"f\s*\{?GEE\}?", "Exposé PDF fGEE Dezimalwert"),
    }
    for field, (pattern, label) in replacements.items():
        found = _value_after_label(text, pattern)
        if not found:
            continue
        raw, value = found
        facts[field] = value
        evidence = [item for item in evidence if item.get("field_name") != field]
        evidence.append(
            {
                "field_name": field,
                "value": value,
                "source_label": label,
                "source_text_snippet": f"{field}: {raw}",
                "confidence": "derived",
            }
        )
    return facts, evidence


def register_parser_quality() -> None:
    global _patched
    if _patched:
        return

    original_willhaben = parser.parse_willhaben
    original_listing = parser.parse_listing
    original_pdf_facts = house_manage.parse_pdf_facts

    def parse_willhaben_fixed(url: str, raw_html: str) -> parser.ParsedListing:
        return _correct_willhaben_energy(original_willhaben(url, raw_html), raw_html)

    def parse_listing_fixed(url: str, raw_html: str) -> parser.ParsedListing:
        if "willhaben.at" in urlparse(url).netloc.lower():
            return parse_willhaben_fixed(url, raw_html)
        return original_listing(url, raw_html)

    def clean_float_fixed(value: object) -> float | None:
        return parse_local_decimal(value)

    def parse_pdf_facts_fixed(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return _correct_pdf_energy(original_pdf_facts, text)

    parser.parse_willhaben = parse_willhaben_fixed
    parser.parse_listing = parse_listing_fixed
    main.parse_listing = parse_listing_fixed
    import_patch.parse_listing = parse_listing_fixed
    house_manage.clean_float = clean_float_fixed
    house_manage.parse_pdf_facts = parse_pdf_facts_fixed
    _patched = True
