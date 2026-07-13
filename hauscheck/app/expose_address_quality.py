from __future__ import annotations

import re

import app.expose_review as expose_review


_ORIGINAL_EXTRACTOR = expose_review.extract_address_proposals
_BLOCKED = re.compile(
    r"\b(?:makler|anbieter|kontakt|impressum|büro|office|kanzlei|immobilien|"
    r"gmbh|kg|e\.u\.|telefon|telefonnummer|e-?mail|homepage|www\.)\b",
    re.IGNORECASE,
)
_LABEL = (
    r"(?P<label>(?i:Objektadresse|Liegenschaftsadresse|Adresse\s+der\s+Liegenschaft|"
    r"Adresse\s+des\s+Objekts|Objektstandort|Standort\s+des\s+Objekts))"
)
_STOP = (
    r"(?i:Kontakt|Makler|Anbieter|Impressum|Telefon|E-?Mail|Email|Homepage|"
    r"Objekt(?:nummer|daten)?|Preis|Kaufpreis|Wohnfläche|Grundstück|Energie|HWB|"
    r"fGEE|Baujahr|Zimmer|Beschreibung)"
)
_NAME_TOKEN = rf"(?!(?:{_STOP})\b)[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]*"
_GENERIC_STREET = rf"(?:{_NAME_TOKEN}\s+){{0,5}}{_NAME_TOKEN}"
_CITY_FIRST = rf"(?!(?:{_STOP})\b)[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]+"
_CITY_NEXT = (
    rf"(?!(?:{_STOP})\b)"
    r"(?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.'\-]+|am|im|an|der|bei|ob|unter)"
)
_CITY = rf"{_CITY_FIRST}(?:\s+{_CITY_NEXT}){{0,5}}"
_LABELLED_PATTERNS = [
    re.compile(
        rf"\b{_LABEL}\s*[:\-]?\s*(?P<street>{_GENERIC_STREET})\s+"
        rf"(?P<number>\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?)\s*,?\s*"
        rf"(?P<zip>[1-9][0-9]{{3}})\s+(?P<city>{_CITY})"
    ),
    re.compile(
        rf"\b{_LABEL}\s*[:\-]?\s*(?P<zip>[1-9][0-9]{{3}})\s+"
        rf"(?P<city>{_CITY})\s*,?\s+(?P<street>{_GENERIC_STREET})\s+"
        rf"(?P<number>\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?)"
    ),
]


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]", "", value.lower())


def _labelled_candidates(text: str) -> list[dict[str, str]]:
    flat = re.sub(r"\s+", " ", str(text or "").replace("\u00a0", " ")).strip()
    result: list[dict[str, str]] = []
    for pattern in _LABELLED_PATTERNS:
        for match in pattern.finditer(flat):
            street = re.sub(r"\s+", " ", match.group("street")).strip()
            city = re.sub(r"\s+", " ", match.group("city")).strip(" ,.;:-")
            if not street or not city or _BLOCKED.search(f"{street} {city}"):
                continue
            address = (
                f"{street} {match.group('number').strip()}, "
                f"{match.group('zip').strip()} {city}"
            )
            context = flat[max(0, match.start() - 120):min(len(flat), match.end() + 180)]
            result.append(
                {
                    "address_text": address,
                    "context_text": context[:500],
                    "confidence": "high",
                }
            )
    return result


def extract_address_proposals(text: str) -> list[dict[str, str]]:
    combined = _labelled_candidates(text) + list(_ORIGINAL_EXTRACTOR(text))
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for proposal in combined:
        address = str(proposal.get("address_text") or "").strip()
        street_part = address.split(",", 1)[0]
        if not address or _BLOCKED.search(street_part):
            continue
        normalized = _key(address)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(proposal)
    result.sort(key=lambda item: 0 if item.get("confidence") == "high" else 1)
    return result[:5]


def register_expose_address_quality() -> None:
    expose_review.extract_address_proposals = extract_address_proposals
