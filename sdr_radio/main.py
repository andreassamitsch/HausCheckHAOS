#!/usr/bin/env python3
"""RTL-SDR WBFM tuner + shared MP3 stream for a Home Assistant app.

The control interface is reachable through authenticated HA Ingress only (8098).
The LAN port (8099) exposes solely /stream.mp3 and /health.
"""
import json
import base64
import hashlib
import socket
import struct
import os
import queue
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from radio_metadata import Metadata, stations_search
from sdr_scan import scan_spectrum, find_next
from rds_state import RDSState
from rtr_catalog import RtrCatalog
from mqtt_bridge import RadioMqttBridge

DATA = Path("/data")
OPTIONS_PATH = Path("/data/options.json")
HTML_PATH = Path("/app/index.html")
DATA.mkdir(parents=True, exist_ok=True)


def load_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return fallback


def save_json(path, value):
    temp = path.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
    temp.replace(path)


OPTIONS = load_json(OPTIONS_PATH, {})
DEVICE = max(0, int(OPTIONS.get("device_index", 0)))
PPM = int(OPTIONS.get("ppm", 0))
GAIN = str(OPTIONS.get("gain", "auto")).strip().lower()
RDS_ENABLED = bool(OPTIONS.get("rds_enabled", True))
STREAM_BASE = str(OPTIONS.get("stream_base_url", "http://homeassistant.local:8099")).rstrip("/")
PRESETS_PATH = DATA / "presets.json"


def checked_frequency(value):
    try:
        freq = round(float(value), 2)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Bitte eine gültige Frequenz eingeben.") from None
    if not 87.5 <= freq <= 108.0:
        raise ValueError("UKW-Frequenz muss zwischen 87,5 und 108,0 MHz liegen.")
    if not abs(freq * 20 - round(freq * 20)) < 0.001:
        raise ValueError("Bitte eine Frequenz in 0,05-MHz-Schritten eingeben.")
    return freq


class Receiver:
    """One SDR tuner, a persistent MP3 encoder, and real-time PCM clients.

    Changing frequency restarts only rtl_fm. The encoder and subscriber
    connections stay alive and receive silence until the new RF signal arrives.
    """

    PCM_RATE = 48000
    PCM_FRAME_MS = 20
    PCM_FRAME_BYTES = PCM_RATE * 2 * PCM_FRAME_MS // 1000
    SILENCE = b"\0" * PCM_FRAME_BYTES

    def __init__(self):
        self.lock = threading.RLock()
        self.session_gen = 0
        self.tuner_gen = 0
        self.radio = None
        self.redsea = None
        self.pcm_converter = None
        self.encoder = None
        self.frequency = None
        self.scanning = False
        self.scan_guard = threading.Lock()
        self.scan_cache = []
        self.scan_time = 0.0
        self.scan_duration_ms = None
        self.subscribers = set()
        self.pcm_subscribers = set()
        self.pcm_queue = queue.Queue(maxsize=8)
        self.errors = deque(maxlen=30)
        self.last_error = ""
        self.total_audio_bytes = 0
        self.last_data_at = None
        self.last_rf_at = None
        self.tune_started_at = None
        self.tune_ready_ms = None
        self.presets = load_json(PRESETS_PATH, [])
        if not isinstance(self.presets, list):
            self.presets = []
        self.presets = self.presets[:50]

    def _running_locked(self):
        return bool(self.radio and self.radio.poll() is None and
                    self.encoder and self.encoder.poll() is None)

    def status(self):
        with self.lock:
            return {
                "running": self._running_locked(),
                "frequency": self.frequency,
                "rds_enabled": RDS_ENABLED,
                "scanning": self.scanning,
                "scan_stations": list(self.scan_cache),
                "scan_duration_ms": self.scan_duration_ms,
                "listeners": len(self.subscribers) + len(self.pcm_subscribers),
                "pcm_listeners": len(self.pcm_subscribers),
                "stream_url": STREAM_BASE + "/stream.mp3",
                "last_error": self.last_error,
                "audio_bytes": self.total_audio_bytes,
                "audio_fresh": bool(self.last_rf_at and time.monotonic() - self.last_rf_at < 2),
                "tune_ready_ms": self.tune_ready_ms,
                "log": list(self.errors)[-8:],
                "presets": list(self.presets),
            }

    def _log_pipe(self, proc, label, generation, tuner=False):
        try:
            for line in iter(proc.stderr.readline, b""):
                msg = line.decode("utf-8", errors="replace").strip()
                if not msg:
                    continue
                with self.lock:
                    if generation == (self.tuner_gen if tuner else self.session_gen):
                        self.errors.append(label + ": " + msg[:500])
                        if any(term in msg.lower() for term in
                               ("error", "failed", "busy", "no supported", "no device")):
                            self.last_error = msg[:500]
                print(label + ": " + msg, flush=True)
        except (OSError, ValueError):
            pass

    def _rds_groups(self, proc, generation, frequency):
        # "--feed-through" prints JSON to stderr, MPX bytes to stdout.
        try:
            for raw in iter(proc.stderr.readline,b""):
                with self.lock:
                    if generation != self.tuner_gen:
                        return
                line = raw.decode("utf-8",errors="replace").strip()
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        group=json.loads(line)
                        rds.feed(group,frequency)
                        continue
                    except (ValueError,TypeError):
                        pass
                if "error" in line.lower():
                    with self.lock:
                        if generation==self.tuner_gen:
                            self.errors.append("RDS: "+line[:250])
                print("RDS:",line[:250],flush=True)
        except (OSError,ValueError):
            pass

    @staticmethod
    def _latest(q, item):
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(item)
            except (queue.Empty, queue.Full):
                pass

    def _mp3_pump(self, proc, generation):
        try:
            while True:
                # Smaller reads avoid accumulating 300+ ms of encoded audio
                # before a subscriber receives the first bytes.
                chunk = proc.stdout.read(1024)
                if not chunk:
                    break
                with self.lock:
                    if generation != self.session_gen:
                        break
                    self.total_audio_bytes += len(chunk)
                    self.last_data_at = time.monotonic()
                    for subscriber in tuple(self.subscribers):
                        self._latest(subscriber, chunk)
        except (OSError, ValueError) as exc:
            print("MP3-Pump:", exc, flush=True)
        finally:
            with self.lock:
                if generation == self.session_gen:
                    self.last_error = self.last_error or "MP3-Encoder wurde beendet."
                    self.errors.append(self.last_error)

    def _pcm_writer(self, proc, generation):
        """Keep the encoder clocked, even while tuning, to preserve MP3 clients."""
        next_tick = time.monotonic()
        try:
            while True:
                with self.lock:
                    if generation != self.session_gen or proc.poll() is not None:
                        break
                try:
                    packet = self.pcm_queue.get(timeout=0.01)
                except queue.Empty:
                    packet = self.SILENCE
                # A frame is always exactly 20ms / 1920 bytes at 48 kHz s16le.
                if len(packet) != self.PCM_FRAME_BYTES:
                    packet = self.SILENCE
                try:
                    proc.stdin.write(packet)
                except (BrokenPipeError, OSError, ValueError):
                    break
                with self.lock:
                    if generation != self.session_gen:
                        break
                    for subscriber in tuple(self.pcm_subscribers):
                        self._latest(subscriber, packet)
                next_tick += self.PCM_FRAME_MS / 1000.0
                delta = next_tick - time.monotonic()
                if delta > 0:
                    time.sleep(delta)
                elif delta < -0.1:
                    next_tick = time.monotonic()
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass

    def _pcm_capture(self, proc, tuner_generation):
        try:
            while True:
                chunk = proc.stdout.read(self.PCM_FRAME_BYTES)
                if not chunk:
                    break
                if len(chunk) != self.PCM_FRAME_BYTES:
                    continue
                with self.lock:
                    if tuner_generation != self.tuner_gen:
                        break
                    now = time.monotonic()
                    self.last_rf_at = now
                    if self.tune_ready_ms is None and self.tune_started_at is not None:
                        self.tune_ready_ms = round((now - self.tune_started_at) * 1000)
                self._latest(self.pcm_queue, chunk)
        except (OSError, ValueError) as exc:
            print("PCM-Capture:", exc, flush=True)
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    @staticmethod
    def _terminate(proc):
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        for fd in (proc.stdout, proc.stderr):
            if fd:
                try:
                    fd.close()
                except (OSError, ValueError):
                    pass

    def _stop_tuner_locked(self):
        self.tuner_gen += 1
        proc = self.radio
        rdsproc = self.redsea
        converter = self.pcm_converter
        self.radio = None
        self.redsea = None
        self.pcm_converter = None
        self.frequency = None
        self.last_rf_at = None
        while True:
            try:
                self.pcm_queue.get_nowait()
            except queue.Empty:
                break
        for process in (proc, rdsproc, converter):
            self._terminate(process)

    def _stop_locked(self):
        self._stop_tuner_locked()
        self.session_gen += 1
        proc = self.encoder
        self.encoder = None
        if proc is not None:
            # Closing encoder stdin unblocks FFmpeg cleanly, if possible.
            try:
                if proc.stdin:
                    proc.stdin.close()
            except (OSError, ValueError):
                pass
            self._terminate(proc)
        self.subscribers.clear()
        self.pcm_subscribers.clear()
        self.total_audio_bytes = 0
        self.last_data_at = None
        self.tune_ready_ms = None

    def stop(self):
        with self.lock:
            self._stop_locked()
            self.last_error = ""

    def _start_encoder_locked(self):
        if self.encoder is not None and self.encoder.poll() is None:
            return
        if self.encoder is not None:
            self._stop_locked()
        ffmpeg = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                  "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", "pipe:0",
                  "-c:a", "libmp3lame", "-b:a", "96k",
                  "-write_xing", "0", "-flush_packets", "1",
                  "-f", "mp3", "pipe:1"]
        self.encoder = subprocess.Popen(ffmpeg, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        bufsize=0)
        generation = self.session_gen
        threading.Thread(target=self._log_pipe,
                         args=(self.encoder, "FFmpeg", generation), daemon=True).start()
        threading.Thread(target=self._mp3_pump,
                         args=(self.encoder, generation), daemon=True).start()
        threading.Thread(target=self._pcm_writer,
                         args=(self.encoder, generation), daemon=True).start()

    def tune(self, value):
        if self.scanning:
            raise ValueError("Sendersuchlauf läuft. Bitte kurz warten.")
        freq = checked_frequency(value)
        with self.lock:
            if self.frequency == freq and self._running_locked():
                return self.status()
            # This encoder, MP3 TCP connections and live PCM connections are
            # intentionally NOT restarted when tuning another frequency.
            self._start_encoder_locked()
            self._stop_tuner_locked()
            self.last_error = ""
            self.errors.clear()
            self.tune_started_at = time.monotonic()
            self.tune_ready_ms = None
            # RDS requires the unfiltered MPX (> 114 kHz to recover
            # the 57-kHz subcarrier); the 48-kHz audio-only path
            # discards RDS. Redsea uses the same SINGLE SDR dongle.
            args = ["rtl_fm", "-d", str(DEVICE),
                    "-M", "fm", "-f", f"{freq:.2f}M",
                    "-s", ("171k" if RDS_ENABLED else "240k"), "-A", "std",
                    "-F", "9", "-l", "0", "-p", str(PPM)]
            if not RDS_ENABLED:
                args += ["-r", "48k", "-E", "deemp", "-E", "dc"]
            if GAIN != "auto":
                try:
                    args += ["-g", str(float(GAIN))]
                except ValueError:
                    raise ValueError("Ungültige Verstärkung.") from None
            try:
                proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
                self.radio = proc
                self.frequency = freq
                generation = self.tuner_gen
                rds.reset(freq)
                threading.Thread(target=self._log_pipe,
                                 args=(proc, "RTL-SDR", generation, True),
                                 daemon=True).start()
                if RDS_ENABLED:
                    # Redsea echoes 171-kHz MPX to stdout and emits RDS
                    # JSON groups to stderr. PCM is resampled *after*
                    # decoding RDS, without changing the MP3 stream URL.
                    redsea = subprocess.Popen(
                        ["redsea", "--input", "mpx", "-r", "171k",
                         "--feed-through", "--output", "json"],
                        stdin=proc.stdout, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
                    proc.stdout.close()
                    self.redsea = redsea
                    converter = subprocess.Popen(
                        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                         "-f", "s16le", "-ar", "171000", "-ac", "1", "-i", "pipe:0",
                         "-af", "lowpass=f=15500,lowpass=f=3183:p=1,aresample=48000",
                         "-f", "s16le", "-ar", "48000", "-ac", "1", "pipe:1"],
                        stdin=redsea.stdout, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
                    redsea.stdout.close()
                    self.pcm_converter = converter
                    threading.Thread(target=self._rds_groups,
                                     args=(redsea, generation, freq),
                                     daemon=True).start()
                    threading.Thread(target=self._log_pipe,
                                     args=(converter, "PCM", generation, True),
                                     daemon=True).start()
                    capture = converter
                else:
                    capture = proc
                threading.Thread(target=self._pcm_capture,
                                 args=(capture, generation), daemon=True).start()
            except OSError as exc:
                self._stop_tuner_locked()
                self.last_error = str(exc)
                raise RuntimeError(str(exc)) from exc
            return self.status()

    def step(self, direction):
        """Manual tuning by one 100-kHz FM channel."""
        if direction not in (-1, 1):
            raise ValueError("Ungültige Richtung.")
        with self.lock:
            start = self.frequency if self.frequency is not None else 99.7
        nxt = round(start * 10 + direction) / 10
        if nxt > 108:
            nxt = 87.5
        elif nxt < 87.5:
            nxt = 108.0
        return self.tune(nxt)

    def band_scan(self, direction=None):
        """One 2-5s sweep; PCM/MP3 encoder remains running through silence.

        Cached station candidates make future Seek button presses fast.
        """
        if not self.scan_guard.acquire(blocking=False):
            raise ValueError("Sendersuchlauf läuft bereits.")
        old = None
        target = None
        exc = None
        try:
            with self.lock:
                old = self.frequency if self.frequency is not None else 99.7
                cache_ok = bool(self.scan_cache) and time.monotonic()-self.scan_time < 3600
                if cache_ok:
                    stations = list(self.scan_cache)
                else:
                    self.scanning = True
                    self._stop_tuner_locked()
            if not cache_ok:
                try:
                    result = scan_spectrum(DEVICE, GAIN, PPM)
                    stations = result["stations"]
                    with self.lock:
                        self.scan_cache = list(stations)
                        self.scan_time = time.monotonic()
                        self.scan_duration_ms = result["duration_ms"]
                except Exception as err:
                    exc = err
            if exc is None:
                if direction is None:
                    target = old
                else:
                    target = find_next(stations, old, direction)
                    if target is None:
                        exc = ValueError("Keinen ausreichend starken Sender gefunden.")
            with self.lock:
                self.scanning = False
            # Restore previous station on a failed scan, otherwise tune chosen.
            self.tune(target if target is not None else old)
            if exc is not None:
                raise RuntimeError(str(exc))
            return self.status()
        finally:
            with self.lock:
                self.scanning = False
            self.scan_guard.release()

    def add_preset(self, name, value):
        name = str(name).strip()[:48]
        if not name:
            raise ValueError("Bitte einen Sendernamen angeben.")
        freq = checked_frequency(value)
        with self.lock:
            self.presets = [x for x in self.presets
                            if not (isinstance(x, dict) and
                                    x.get("name", "").casefold() == name.casefold())]
            if len(self.presets) >= 50:
                raise ValueError("Maximal 50 Favoriten.")
            self.presets.append({"name": name, "frequency": freq})
            save_json(PRESETS_PATH, self.presets)
            return self.status()

    def remove_preset(self, name):
        with self.lock:
            self.presets = [x for x in self.presets
                            if not (isinstance(x, dict) and x.get("name") == name)]
            save_json(PRESETS_PATH, self.presets)
            return self.status()

    def probe(self):
        with self.lock:
            if self.radio and self.radio.poll() is None:
                return {"ok": True, "message": "USB-Stick wird bereits vom SDR-Radio genutzt."}
        try:
            result = subprocess.run(["rtl_test", "-t", "-d", str(DEVICE)],
                                    capture_output=True, text=True, timeout=9)
            output = (result.stdout + result.stderr).strip()[-2400:]
            return {"ok": result.returncode == 0, "message": output or
                    "Keine Geräteinformation zurückgegeben."}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "USB-Test hat das Zeitlimit überschritten."}
        except OSError as exc:
            return {"ok": False, "message": str(exc)}


radio = Receiver()
metadata = Metadata()
rds = RDSState()
rtr = RtrCatalog()
threading.Thread(target=rtr.refresh,daemon=True).start()

def view_status():
    data = radio.status()
    data.update(metadata.status())
    data.update(rds.status())
    current = data["frequency"]
    rs = data["rds"]
    if current is not None:
        match = rtr.match(current,rs.get("pi",""),rs.get("ps",""))
        data["rtr_matches"]=match[:6]
    else:
        data["rtr_matches"]=[]
    station=data.get("station") or {}
    verified = (data["rtr_matches"][0] if data["rtr_matches"] and rs.get("pi")
                and data["rtr_matches"][0].get("pi") == rs["pi"] else None)
    if verified:
        data["station"]={**station,"name":verified["program"]}
        data["station_name_source"]="RDS PI + RTR (PS: "+(rs.get("ps") or "–")+")"
    elif rs.get("ps"):
        data["station"]={**station,"name":rs["ps"]}
        data["station_name_source"]="RDS PS"
    elif not station and data["rtr_matches"]:
        data["station"]={"name":data["rtr_matches"][0]["program"]}
        data["station_name_source"]="RTR (Standortprognose)"
    else:
        data["station_name_source"]="manuelle Zuordnung" if station else None
    if data.get("rds_song"):
        data["song"]=data["rds_song"]
    elif data.get("song"):
        data["song"]={**data["song"],"source":"Online-Fallback (keine RDS-Titel)"}
    return data

def tuned_status():
    metadata.set_frequency(radio.status()["frequency"])
    output.update_frequency(radio.status()["frequency"])
    return view_status()


def ha_request(path, payload=None):
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt – Home-Assistant-API nicht verfügbar.")
    request = urllib.request.Request(
        "http://supervisor/core/api/" + path,
        data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"},
        method=("POST" if payload is not None else "GET"))
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError) as exc:
        raise RuntimeError("Home-Assistant-API: " + str(exc)) from exc


class RadioOutput:
    """Selection and manual output ownership. Never auto-resume a stopped player."""
    def __init__(self):
        self.lock = threading.RLock()
        data = load_json(DATA / "output.json", {})
        output = str(data.get("entity_id") or "media_player.ultra_slim_soundbar")
        self.selected = output if output.startswith("media_player.") else "media_player.ultra_slim_soundbar"
        self.active = None
        self.last_play_at = 0.0
        self.last_frequency = float(data.get("last_frequency") or 99.7)

    def save(self):
        with self.lock:
            save_json(DATA / "output.json",
                      {"entity_id": self.selected,
                       "last_frequency": self.last_frequency})

    def select(self, entity):
        entity = str(entity or "")
        if not entity.startswith("media_player.") or len(entity) > 140:
            raise ValueError("Ungültiges Ausgabegerät.")
        with self.lock:
            self.selected = entity
            self.save()

    def update_frequency(self, freq):
        if freq is None:
            return
        with self.lock:
            if self.last_frequency != freq:
                self.last_frequency = float(freq)
                self.save()

    def snapshot(self):
        with self.lock:
            return {"selected_output": self.selected,
                    "active_output": self.active,
                    "last_frequency": self.last_frequency}

    def output_state(self):
        selected = self.selected
        try:
            player = ha_request("states/" + selected)
            state = str(player.get("state", "unknown"))
            volume = player.get("attributes", {}).get("volume_level")
            media_id = str(player.get("attributes", {}).get("media_content_id") or "")
        except (RuntimeError, KeyError, ValueError):
            state, volume, media_id = "unavailable", None, ""
        # A physical stop is final. There is no watchdog/resume playback.
        with self.lock:
            playing = state in ("playing", "buffering")
            if self.active == selected and state in ("idle", "off", "paused", "unavailable"):
                # Give a slow speaker time to wake after an explicit user Play.
                # Once running, an external Stop stays stopped (never auto-play).
                if time.monotonic() - self.last_play_at > 12:
                    self.active = None
            active = self.active == selected and playing
        return {"output_state": state, "output_volume": volume,
                "output_playing": active,
                "output_media_id": media_id}

    def play(self, target):
        if target:
            self.select(target)
        with self.lock:
            selected = self.selected
            previous = self.active
            preferred_frequency = self.last_frequency
        state = radio.status()
        if not state["running"]:
            radio.tune(preferred_frequency)
            metadata.set_frequency(preferred_frequency)
        if previous and previous != selected:
            try:
                ha_request("services/media_player/media_stop", {"entity_id": previous})
            except RuntimeError:
                pass
        # ONLY a human-triggered "play" command calls this service.
        ha_request("services/media_player/play_media", {
            "entity_id": selected,
            "media_content_id": STREAM_BASE + "/stream.mp3",
            "media_content_type": "music"})
        with self.lock:
            self.active = selected
            self.last_play_at = time.monotonic()

    def stop(self, target=None):
        with self.lock:
            entity = target or self.selected
            active = self.active
        if not str(entity).startswith("media_player."):
            raise ValueError("Ungültiges Ausgabegerät.")
        ha_request("services/media_player/media_stop", {"entity_id": entity})
        with self.lock:
            if entity == active:
                self.active = None


output = RadioOutput()


def mqtt_radio_state():
    result = view_status()
    result.update(output.snapshot())
    result.update(output.output_state())
    # Enrich saved favorites with available station logos, without uploading media.
    for favorite in result.get("presets", []):
        if not isinstance(favorite, dict):
            continue
        try:
            freq = float(favorite["frequency"])
            station = metadata.station(freq)
            favorite["logo"] = station.get("favicon") or ""
            favorite["station_name"] = station.get("name") or favorite.get("name")
        except (ValueError, KeyError, TypeError):
            continue
    return result


def mqtt_radio_command(action, data):
    direction = int(data.get("direction", 0))
    if action == "tune":
        freq = checked_frequency(data.get("frequency"))
        radio.tune(freq)
        metadata.set_frequency(freq)
        output.update_frequency(freq)
    elif action == "seek":
        radio.band_scan(direction)
        freq = radio.status()["frequency"]
        metadata.set_frequency(freq)
        output.update_frequency(freq)
    elif action == "step":
        radio.step(direction)
        freq = radio.status()["frequency"]
        metadata.set_frequency(freq)
        output.update_frequency(freq)
    elif action == "select_output":
        output.select(data.get("entity_id"))
    elif action == "play":
        output.play(data.get("entity_id"))
    elif action == "stop_output":
        output.stop(data.get("entity_id"))
    elif action == "stop_tuner":
        output.stop()
        radio.stop()
        metadata.set_frequency(None)
    elif action == "add_favorite":
        freq = radio.status()["frequency"]
        if freq is None:
            raise ValueError("Bitte zuerst einen Sender einstellen.")
        station = view_status().get("station") or {}
        name = str(data.get("name") or station.get("name") or f"{freq:.1f} MHz").strip()
        radio.add_preset(name, freq)
        mapped = metadata.station(freq)
        if not mapped.get("favicon") and name:
            # Conservative logo lookup: only auto-associate a strongly matching
            # Austrian directory result with the current FM channel.
            from radio_metadata import key as normalize
            candidates = stations_search(name)
            expected = normalize(name)
            exact = next((s for s in candidates if
                          normalize(s.get("name")) in (expected, expected+"hq")
                          and s.get("favicon")), None)
            if exact:
                metadata.bind(freq, exact)
    elif action == "remove_favorite":
        radio.remove_preset(str(data.get("name", "")))


class Handler(BaseHTTPRequestHandler):
    public_stream_only = False
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        if "/stream.mp3" not in self.path:
            print("HTTP " + (fmt % args), flush=True)

    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            state = radio.status()
            return self.reply(200, {"running": state["running"],
                                     "frequency": state["frequency"]})
        if path == "/stream.mp3":
            return self.stream()
        if path == "/pcm" and not self.public_stream_only:
            return self.pcm_websocket()
        if self.public_stream_only:
            return self.reply(404, {"error": "Nicht verfügbar"})
        if path in ("/", "/index.html"):
            body = HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self.reply(200, view_status())
        elif path == "/api/players":
            try:
                devices = ha_request("states")
                self.reply(200, [
                    {"entity_id": v["entity_id"],
                     "name": v.get("attributes", {}).get("friendly_name", v["entity_id"])}
                    for v in devices
                    if v.get("entity_id", "").startswith("media_player.")
                    and v.get("state") != "unavailable"
                ])
            except RuntimeError as exc:
                self.reply(502, {"error": str(exc)})
        elif path == "/api/probe":
            self.reply(200, radio.probe())
        elif path == "/api/rtr":
            self.reply(200, rtr.status())
        else:
            self.reply(404, {"error": "Unbekannter Pfad"})

    def do_POST(self):
        if self.public_stream_only:
            return self.reply(405, {"error": "Nur Livestream über diesen Port"})
        path = urlsplit(self.path).path
        if path not in ("/api/tune", "/api/stop", "/api/preset",
                        "/api/remove_preset", "/api/ha_play", "/api/ha_stop",
                        "/api/step", "/api/seek", "/api/scan",
                        "/api/stations_search", "/api/station_bind",
                        "/api/station_clear", "/api/rtr_refresh"):
            return self.reply(404, {"error": "Unbekannter Pfad"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > 8192:
                return self.reply(413, {"error": "Zu große Anfrage"})
            data = json.loads(self.rfile.read(n)) if n else {}
            if not isinstance(data, dict):
                raise ValueError("Ungültige Anfrage")
            if path == "/api/tune":
                radio.tune(data.get("frequency"))
                out = tuned_status()
            elif path == "/api/step":
                radio.step(int(data.get("direction", 0)))
                out = tuned_status()
            elif path == "/api/seek":
                radio.band_scan(int(data.get("direction", 0)))
                out = tuned_status()
            elif path == "/api/scan":
                radio.band_scan()
                out = tuned_status()
            elif path == "/api/rtr_refresh":
                out = rtr.refresh(force=True)
            elif path == "/api/stations_search":
                out = {"stations": stations_search(data.get("name", ""))}
            elif path == "/api/station_bind":
                freq = checked_frequency(data.get("frequency"))
                metadata.bind(freq, data.get("station") or {})
                out = view_status()
            elif path == "/api/station_clear":
                freq = checked_frequency(data.get("frequency"))
                metadata.clear(freq)
                out = view_status()
            elif path == "/api/stop":
                radio.stop()
                metadata.set_frequency(None)
                out = view_status()
            elif path == "/api/preset":
                out = radio.add_preset(data.get("name", ""), data.get("frequency"))
            elif path == "/api/remove_preset":
                out = radio.remove_preset(str(data.get("name", "")))
            else:
                entity_id = str(data.get("entity_id", ""))
                if not entity_id.startswith("media_player.") or len(entity_id) > 150:
                    raise ValueError("Ungültiges Wiedergabegerät.")
                if path == "/api/ha_play":
                    if not radio.status()["running"]:
                        raise ValueError("Radioempfang zuerst starten.")
                    if urlsplit(STREAM_BASE).scheme not in ("http", "https"):
                        raise ValueError("stream_base_url muss eine HTTP(S)-Adresse sein.")
                    out = ha_request("services/media_player/play_media", {
                        "entity_id": entity_id, "media_content_id":
                        STREAM_BASE + "/stream.mp3", "media_content_type": "music"})
                else:
                    out = ha_request("services/media_player/media_stop",
                                     {"entity_id": entity_id})
            self.reply(200, {"ok": True, "result": out})
        except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            self.reply(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def stream(self):
        with radio.lock:
            if not radio._running_locked():
                return self.reply(503, {"error": radio.last_error or "Empfang nicht aktiv"})
            q = queue.Queue(maxsize=6)
            generation = radio.session_gen
            radio.subscribers.add(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store, no-cache")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("icy-name", "SDR UKW Radio")
            self.end_headers()
            while True:
                with radio.lock:
                    if generation != radio.session_gen or radio.encoder is None:
                        break
                try:
                    data = q.get(timeout=0.5)
                    self.wfile.write(data)
                    self.wfile.flush()
                except queue.Empty:
                    continue
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with radio.lock:
                radio.subscribers.discard(q)

    def pcm_websocket(self):
        """20ms PCM frames over authenticated HA Ingress, never public LAN port."""
        key = self.headers.get("Sec-WebSocket-Key", "")
        if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
            return self.reply(426, {"error": "WebSocket erforderlich"})
        with radio.lock:
            if not radio._running_locked():
                return self.reply(503, {"error": "Empfang nicht aktiv"})
            q = queue.Queue(maxsize=6)
            generation = radio.session_gen
            radio.pcm_subscribers.add(q)
        accept = base64.b64encode(hashlib.sha1((
            key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        ).encode("ascii")).digest()).decode("ascii")
        try:
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            while True:
                with radio.lock:
                    if generation != radio.session_gen or radio.encoder is None:
                        break
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                # Binary, unmasked server-to-client RFC6455 frame (1920 bytes).
                header = b"\x82\x7e" + struct.pack("!H", len(data))
                self.connection.sendall(header + data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with radio.lock:
                radio.pcm_subscribers.discard(q)



def server(port, public):
    class BoundHandler(Handler):
        public_stream_only = public
    httpd = ThreadingHTTPServer(("0.0.0.0", port), BoundHandler)
    httpd.daemon_threads = True
    print("SDR Radio: " + ("Stream" if public else "Ingress") +
          " läuft auf Port " + str(port), flush=True)
    return httpd


def main():
    bridge = RadioMqttBridge(mqtt_radio_state, mqtt_radio_command)
    servers = [server(8098, False), server(8099, True)]
    for httpd in servers:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    def terminate(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        radio.stop()
        for httpd in servers:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    main()
