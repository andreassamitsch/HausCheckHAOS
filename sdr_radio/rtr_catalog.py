"""RTR's official frequency book, scoped to Wies (Steiermark).

This is a frequency ALLOCATION / transmitter listing, NOT verified
reception. The actual SDR scan determines which stations are audible.
Source used in Dudu7:
https://data.rtr.at/api/v1/tables/MedienFrequenzbuch.json
and https://senderkataster.rtr.at/programs/
"""
import json
import math
import re
import threading
import time
import urllib.request

RTR_URL = "https://data.rtr.at/api/v1/tables/MedienFrequenzbuch.json"
RTR_SENDERKATASTER = "https://senderkataster.rtr.at/programs/"
WIES_LAT, WIES_LON = 46.72028, 15.27194
MAX_DISTANCE_KM = 100.0


def coords(raw):
    s = str(raw or "").strip().upper().replace(",", ".")
    try:
        v = float(s)
        if math.isfinite(v) and abs(v) <= 180:
            return v
    except ValueError:
        pass
    # RTR coordinates include DMS strings such as 46N43 10.0
    m = re.match(r"^(\d{1,3})\s*([NSEW])\s*(\d{1,2})[^0-9.]+(\d{1,2}(?:\.\d+)?)$", s)
    if m:
        deg, direction, minute, second = m.groups()
        v = int(deg) + int(minute)/60 + float(second)/3600
        return -v if direction in ("S", "W") else v
    m = re.match(r"^(\d{1,3})[^0-9.]+(\d{1,2})[^0-9.]+(\d{1,2}(?:\.\d+)?)\s*([NSEW])$", s)
    if m:
        deg, minute, second, direction = m.groups()
        v = int(deg) + int(minute)/60 + float(second)/3600
        return -v if direction in ("S", "W") else v
    return None


def haversine(lat1, lon1, lat2, lon2):
    radius = 6371.0
    a,b,c,d = map(math.radians, (lat1,lon1,lat2,lon2))
    z = math.sin((c-a)/2)**2 + math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 2*radius*math.asin(min(1, math.sqrt(z)))


def get_rows():
    errors = []
    for source in (RTR_URL, RTR_SENDERKATASTER):
        try:
            req = urllib.request.Request(source,headers={"User-Agent":"HausCheckSDR/0.4","Accept":"application/json"})
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read(20_000_000).decode("utf-8"))
            raw = data.get("data") if "MedienFrequenzbuch" in source else data.get("programs")
            if isinstance(raw, str):
                raw = json.loads(raw)
            if isinstance(raw, list) and len(raw) >= 100:
                return raw, source
            errors.append(source + " invalid response")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(source + " " + str(exc)[:90])
    raise RuntimeError("RTR-Katalog momentan nicht erreichbar: " + "; ".join(errors))


def get(row, *names):
    for name in names:
        val = row.get(name)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def parse(rows):
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = get(row,"rtr_programm_typ","programm_typ").lower()
        if not ("ukw" in kind or "analog" in kind):
            continue
        try:
            freq = float(get(row,"rtr_funkst_frequenz","funkst_frequenz").replace(",", "."))
        except ValueError:
            continue
        if not 87.5 <= freq <= 108.0:
            continue
        lat = coords(get(row,"rtr_funkst_nord","funkst_nord"))
        lon = coords(get(row,"rtr_funkst_ost","funkst_ost"))
        if lat is None or lon is None:
            continue
        distance = haversine(WIES_LAT,WIES_LON,lat,lon)
        if distance > MAX_DISTANCE_KM:
            continue
        name = get(row,"rtr_programm","programm_liste")
        program = get(row,"programm_liste","rtr_programm")
        loc = get(row,"rtr_funkst_name","funkst_name")
        site = get(row,"rtr_funkst_standort","funkst_standort")
        pi = get(row,"rtr_funkst_rds","funkst_rds")
        kw = get(row,"rtr_funkst_leistung_kw","funkst_leistung_kw")
        output.append({"frequency":round(freq,2),
                       "program": program or name,
                       "transmitter":loc,
                       "site":site,
                       "pi":pi.upper() if re.fullmatch(r"[0-9A-Fa-f]{4}",pi) else "",
                       "distance_km":round(distance,1),
                       "erp_kw":kw, "latitude":lat,"longitude":lon})
    return sorted(output,key=lambda r:(r["frequency"],r["distance_km"]))


class RtrCatalog:
    def __init__(self):
        self.lock=threading.RLock()
        self.data=[]
        self.source=""
        self.updated=0.0
        self.error=""
        self.loading=False

    def refresh(self, force=False):
        with self.lock:
            if not force and self.data and time.time()-self.updated<86400:
                return self.status()
            if self.loading:
                return self.status()
            self.loading=True
        try:
            rows, source = get_rows()
            data=parse(rows)
            with self.lock:
                if len(data)<8:
                    raise ValueError("RTR lieferte nur "+str(len(data))+" passende Frequenzen (Schema prüfen).")
                self.data=data
                self.source=source
                self.updated=time.time()
                self.error=""
        except (OSError, ValueError, RuntimeError) as exc:
            with self.lock:
                self.error=str(exc)
        finally:
            with self.lock:
                self.loading=False
        return self.status()

    def status(self):
        with self.lock:
            return {"stations":list(self.data),"source":self.source,
                    "updated_at":self.updated,"error":self.error,
                    "loading":self.loading,"location":"Wies, Steiermark",
                    "radius_km":MAX_DISTANCE_KM}
    def match(self, freq, pi="", ps=""):
        with self.lock:
            matches=[x for x in self.data if abs(x["frequency"]-freq)<0.051]
        if pi:
            p=[x for x in matches if x["pi"]==pi]
            if p:return sorted(p,key=lambda x:x["distance_km"])
        return sorted(matches,key=lambda x:x["distance_km"])
