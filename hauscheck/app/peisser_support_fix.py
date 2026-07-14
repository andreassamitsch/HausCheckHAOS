from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from fastapi import FastAPI

import app.immoscout_support as support
import app.main as main
import app.peisser_support as peisser


_PATCHED = False
_ORIGINAL_PARSE = peisser.parse_peisser


def title_from_url_fixed(url: str) -> str:
    if peisser.is_peisser_url(url):
        entry_id = peisser.peisser_entry_id(url)
        return f"Peisser Immobilien Exposé {entry_id}" if entry_id else "Peisser Immobilien Inserat"
    if support._ORIGINAL_TITLE_FROM_URL:
        return support._ORIGINAL_TITLE_FROM_URL(url)
    return str(url or "")


def parse_peisser_fixed(url: str, raw_html: str):
    result = _ORIGINAL_PARSE(url, raw_html)
    entry_id = peisser.peisser_entry_id(url)
    soup = BeautifulSoup(raw_html, "html.parser")
    gallery = soup.select_one("section[data-peisser-view='gallery']") or soup
    images: dict[str, int] = {}
    for node in gallery.find_all(["a", "img"]):
        raw = node.get("href") or node.get("src")
        if not raw:
            continue
        absolute = urljoin(result.source_url, str(raw))
        match = re.search(
            rf"/data/{re.escape(str(entry_id or ''))}/img_([0-9]+)\.(?:jpe?g|png|webp)(?:\?|$)",
            absolute,
            re.I,
        )
        if match:
            images[absolute.split("?", 1)[0]] = int(match.group(1))
    result.image_urls = [url for url, _index in sorted(images.items(), key=lambda item: item[1])]
    if result.image_urls:
        result.warnings = [item for item in result.warnings if item != "Keine Peisser-Galeriebilder erkannt"]
    return result


def register_peisser_support_fix(app: FastAPI) -> None:
    global _PATCHED
    if _PATCHED:
        return
    peisser.title_from_url_all = title_from_url_fixed
    peisser.parse_peisser = parse_peisser_fixed
    support.title_from_listing_url_multi = title_from_url_fixed
    main.title_from_listing_url = title_from_url_fixed
    _PATCHED = True
