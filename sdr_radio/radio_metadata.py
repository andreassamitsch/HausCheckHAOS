"""Online station identification and now-playing metadata for SDR Radio.

FM audio ALWAYS comes from the RTL-SDR USB dongle. Online streams are
read only for station artwork and optional ICY song metadata.

No album art or MP3 data is saved to disk. Only user station bindings
are stored as a small JSON file in /data.
"""
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RADIO_BROWSER = (
    "https://de1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
)
CLIENT = "HausCheckSDRRadio/0.3 (Home Assistant; radio metadata)"
ALLOWED_MAX = 240_000


def fetch_bytes(url, headers=None, limit=ALLOWED_MAX, timeout=5):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("Ungültige HTTP(S)-Adresse")
    if parts.username or parts.password:
        raise ValueError("Adressen mit Anmeldedaten sind nicht erlaubt")
    request = urllib.request.Request(
        url, headers={"User-Agent": CLIENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(limit)


def fetch_json(url, timeout=5):
    return json.loads(fetch_bytes(url, timeout=timeout).decode("utf-8"))


def clean(x, maxlen=180):
    return str(x or "").strip()[:maxlen]


def key(x):
    return "".join(c for c in unicodedata.normalize("NFKD", str(x or "").casefold())
                   if c.isalnum())


def candidate(s):
    url = clean(s.get("url_resolved") or s.get("url"), 1000)
    icon = clean(s.get("favicon"), 1000)
    if not url.startswith(("http://", "https://")):
        url = ""
    if not icon.startswith(("http://", "https://")):
        icon = ""
    return {
        "uuid": clean(s.get("stationuuid") or s.get("uuid"), 80),
        "name": clean(s.get("name"), 100),
        "favicon": icon,
        "url": url,
        "countrycode": clean(s.get("countrycode"), 3),
        "homepage": clean(s.get("homepage"), 300),
        "votes": int(s.get("votes") or 0)
    }


def stations_search(text):
    name = clean(text, 100)
    if len(name) < 2:
        return []
    query = urllib.parse.urlencode({
        "name": name, "countrycode": "AT", "hidebroken": "true",
        "order": "votes", "reverse": "true", "limit": 30
    })
    for base in RADIO_BROWSER:
        try:
            data = fetch_json(base + "/json/stations/search?" + query, timeout=5)
            out = [candidate(x) for x in data if x.get("name")]
            return out
        except (OSError, ValueError, urllib.error.URLError, KeyError) as exc:
            print("RadioBrowser", exc, flush=True)
    return []


def current_icy(stream_url):
    """Read one ICY metadata block without keeping/download caching the stream."""
    if not stream_url:
        return None
    parts = urllib.parse.urlsplit(stream_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    request = urllib.request.Request(stream_url, headers={
        "User-Agent": CLIENT, "Icy-MetaData": "1",
        "Accept": "*/*", "Connection": "close"
    })
    try:
        with urllib.request.urlopen(request, timeout=6) as resp:
            metaint = int(resp.headers.get("icy-metaint") or 0)
            if not 0 < metaint < 5_000_000:
                return None
            pending = metaint
            while pending:
                chunk = resp.read(min(pending, 8192))
                if not chunk:
                    return None
                pending -= len(chunk)
            count = resp.read(1)
            if not count:
                return None
            size = count[0] * 16
            if not size:
                return None
            raw = resp.read(min(size, 4080)).decode("utf-8", errors="replace")
            match = re.search(r"StreamTitle=['\"](.*?)['\"];", raw, flags=re.I | re.S)
            if match:
                text = clean(match.group(1).strip("\x00 ").replace("\\'", "'"), 250)
                if text and text.lower() not in ("unknown", "advertisement", "live"):
                    return text
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        print("ICY metadata:", str(exc)[:180], flush=True)
    return None


def parse_song(raw):
    """Avoid inventing song titles from radio programme IDs."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    # Most ICY servers use 'Artist - Title'. Some send an ad/station ID:
    if " - " not in text:
        return None
    artist, title = text.split(" - ", 1)
    artist, title = clean(artist, 100), clean(title, 130)
    if len(artist) < 2 or len(title) < 2:
        return None
    if any(x in text.lower() for x in ("werbung", "advert", "livestream", "streaming")):
        return None
    return {"artist": artist, "title": title, "cover_url": "", "source": "ICY (Online-Stream)"}


def artwork_for(artist, title):
    """Cover lookup like a music player, using matching song metadata."""
    query = urllib.parse.urlencode({
        "term": (artist + " " + title)[:170],
        "media": "music", "entity": "song", "country": "AT",
        "limit": 12
    })
    try:
        data = fetch_json("https://itunes.apple.com/search?" + query, timeout=5)
    except (OSError, ValueError, urllib.error.URLError):
        return ""
    candidates = data.get("results", []) if isinstance(data, dict) else []
    a, t = key(artist), key(title)
    for item in candidates:
        ia, it = key(item.get("artistName")), key(item.get("trackName"))
        # Exact matches first; allow mild spelling differences, not unrelated songs.
        if (a == ia or a in ia or ia in a) and (t == it or t in it or it in t):
            cover = clean(item.get("artworkUrl100"), 1000)
            if cover.startswith("https://"):
                return re.sub(r"100x100", "600x600", cover)
    return ""


class Metadata:
    def __init__(self, folder="/data"):
        self.path = Path(folder) / "stations.json"
        self.lock = threading.RLock()
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            self.bindings = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            self.bindings = {}
        self.frequency = None
        self.generation = 0
        self.now = None
        self.last_update = 0.0
        self.last_lookup = 0.0
        self.error = ""
        self.alive = True
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def set_frequency(self, freq):
        with self.lock:
            if self.frequency != freq:
                self.frequency = freq
                self.generation += 1
                self.now = None
                self.last_update = 0
                self.last_lookup = 0
                self.error = ""

    def station(self, freq=None):
        with self.lock:
            f = self.frequency if freq is None else freq
            return dict(self.bindings.get(f"{f:.2f}", {})) if f is not None else {}

    def status(self):
        with self.lock:
            station = dict(self.bindings.get(f"{self.frequency:.2f}", {})) if self.frequency is not None else {}
            return {"station": station,
                    "song": dict(self.now) if self.now else None,
                    "metadata_updated_at": self.last_update,
                    "metadata_error": self.error,
                    "metadata_source": "Online-Stream" if station else None}

    def bind(self, freq, item):
        if not 87.5 <= float(freq) <= 108:
            raise ValueError("Ungültige UKW-Frequenz")
        item = candidate(item)
        if not item.get("uuid") or not item.get("name"):
            raise ValueError("Bitte einen Sender aus der Suche auswählen.")
        with self.lock:
            self.bindings[f"{freq:.2f}"] = item
            self.path.parent.mkdir(exist_ok=True, parents=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.bindings, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            self.generation += 1
            self.now = None
            self.last_lookup = 0
            self.last_update = 0
        return item

    def clear(self, freq):
        with self.lock:
            self.bindings.pop(f"{freq:.2f}", None)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.bindings, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            self.generation += 1
            self.now = None
        return {}

    def _run(self):
        cache = {}
        while self.alive:
            with self.lock:
                freq = self.frequency
                generation = self.generation
                station = dict(self.bindings.get(f"{freq:.2f}", {})) if freq is not None else {}
                due = time.monotonic() - self.last_lookup >= 18
            if not station or not due:
                time.sleep(1)
                continue
            raw = current_icy(station.get("url", ""))
            song = parse_song(raw)
            if song:
                k = key(song["artist"]) + "/" + key(song["title"])
                if k in cache:
                    song["cover_url"] = cache[k]
                else:
                    song["cover_url"] = artwork_for(song["artist"], song["title"])
                    cache[k] = song["cover_url"]
                    if len(cache) > 80:
                        cache.pop(next(iter(cache)))
            with self.lock:
                if generation == self.generation:
                    self.now = song
                    self.last_lookup = time.monotonic()
                    self.last_update = time.time()
                    self.error = ("" if song else
                        "Dieser Sender liefert aktuell keine erkennbaren Songdaten im Online-Stream.")
            time.sleep(1)
