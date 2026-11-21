#!/usr/bin/env python3
"""RTL-SDR WBFM tuner + shared MP3 stream for a Home Assistant app.

The control interface is reachable through authenticated HA Ingress only (8098).
The LAN port (8099) exposes solely /stream.mp3 and /health.
"""
import json
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
    def __init__(self):
        self.lock = threading.RLock()
        self.gen = 0
        self.radio = None
        self.encoder = None
        self.frequency = None
        self.subscribers = set()
        self.errors = deque(maxlen=30)
        self.last_error = ""
        self.total_audio_bytes = 0
        self.last_data_at = None
        self.presets = load_json(PRESETS_PATH, [])
        if not isinstance(self.presets, list):
            self.presets = []
        self.presets = self.presets[:50]

    def status(self):
        with self.lock:
            running = bool(self.radio and self.radio.poll() is None
                           and self.encoder and self.encoder.poll() is None)
            return {
                "running": running,
                "frequency": self.frequency,
                "listeners": len(self.subscribers),
                "stream_url": STREAM_BASE + "/stream.mp3",
                "last_error": self.last_error,
                "audio_bytes": self.total_audio_bytes,
                "audio_fresh": bool(self.last_data_at and time.time() - self.last_data_at < 5),
                "log": list(self.errors)[-8:],
                "presets": list(self.presets),
            }

    def _log_pipe(self, proc, label, generation):
        try:
            for line in iter(proc.stderr.readline, b""):
                msg = line.decode("utf-8", errors="replace").strip()
                if not msg:
                    continue
                with self.lock:
                    if generation == self.gen:
                        self.errors.append(label + ": " + msg[:500])
                        if any(term in msg.lower() for term in ("error", "failed", "busy", "no supported", "no device")):
                            self.last_error = msg[:500]
                print(label + ": " + msg, flush=True)
        except (OSError, ValueError):
            pass

    def _pump(self, proc, generation):
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                with self.lock:
                    if generation != self.gen:
                        break
                    self.total_audio_bytes += len(chunk)
                    self.last_data_at = time.time()
                    for subscriber in tuple(self.subscribers):
                        try:
                            subscriber.put_nowait(chunk)
                        except queue.Full:
                            try:
                                subscriber.get_nowait()
                                subscriber.put_nowait(chunk)
                            except (queue.Empty, queue.Full):
                                pass
        except (OSError, ValueError) as exc:
            print("Audio-Pump:", exc, flush=True)
        finally:
            with self.lock:
                if generation == self.gen:
                    if not self.last_error:
                        self.last_error = "Radiostream beendet. USB-Verbindung und Empfang prüfen."
                    self.errors.append(self.last_error)

    def _stop_locked(self):
        self.gen += 1
        procs = (self.encoder, self.radio)
        self.encoder = None
        self.radio = None
        self.frequency = None
        self.total_audio_bytes = 0
        self.last_data_at = None
        self.subscribers.clear()
        for proc in procs:
            if proc is not None and proc.poll() is None:
                proc.terminate()
        for proc in procs:
            if proc is not None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
                try:
                    if proc.stdout:
                        proc.stdout.close()
                    if proc.stderr:
                        proc.stderr.close()
                except OSError:
                    pass

    def stop(self):
        with self.lock:
            self._stop_locked()
            self.last_error = ""

    def tune(self, value):
        freq = checked_frequency(value)
        with self.lock:
            self._stop_locked()
            self.errors.clear()
            self.last_error = ""
            # 240 kHz -> 48 kHz is an exact 5:1 decimation.  The old
            # WBFM preset (170 kHz -> 32 kHz) can alias strong FM
            # multiplex components into the audible range.
            # Do NOT use -o 4 here: it requests an unsupported 3.84 MS/s\n            # input rate in this rtl_fm build.\n            # Use the standard atan demodulator and 9-tap FIR instead
            # of the faster, lower-quality WBFM defaults.
            args = ["rtl_fm", "-d", str(DEVICE),
                    "-M", "fm", "-f", f"{freq:.2f}M",
                    "-s", "240k", "-A", "std",
                    "-F", "9", "-r", "48k", "-l", "0",
                    "-E", "deemp", "-E", "dc",
                    "-p", str(PPM)]
            if GAIN != "auto":
                try:
                    args += ["-g", str(float(GAIN))]
                except ValueError:
                    raise ValueError("Ungültige Verstärkungseinstellung.") from None
            ffmpeg = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                      "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", "pipe:0",
                      "-c:a", "libmp3lame", "-b:a", "96k",
                      "-write_xing", "0", "-f", "mp3", "pipe:1"]
            try:
                self.radio = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.encoder = subprocess.Popen(
                    ffmpeg, stdin=self.radio.stdout, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
                self.radio.stdout.close()  # FFmpeg owns the read end.
                generation = self.gen
                self.frequency = freq
                for proc, label in ((self.radio, "RTL-SDR"), (self.encoder, "FFmpeg")):
                    threading.Thread(target=self._log_pipe,
                                     args=(proc, label, generation),
                                     daemon=True).start()
                threading.Thread(target=self._pump,
                                 args=(self.encoder, generation),
                                 daemon=True).start()
            except OSError as exc:
                self._stop_locked()
                self.last_error = str(exc)
                raise RuntimeError(str(exc)) from exc
        # Detect the common "device not found / already busy" failure early.
        time.sleep(0.45)
        state = self.status()
        if not state["running"]:
            raise RuntimeError(state["last_error"] or
                               "Empfänger nicht verfügbar. USB-Passthrough prüfen.")
        return state

    def add_preset(self, name, value):
        name = str(name).strip()[:48]
        if not name:
            raise ValueError("Bitte einen Sendernamen angeben.")
        freq = checked_frequency(value)
        with self.lock:
            if len(self.presets) >= 50:
                raise ValueError("Maximal 50 Favoriten.")
            self.presets = [x for x in self.presets
                            if not (isinstance(x, dict)
                                    and x.get("name", "").casefold() == name.casefold())]
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
            self.reply(200, radio.status())
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
        else:
            self.reply(404, {"error": "Unbekannter Pfad"})

    def do_POST(self):
        if self.public_stream_only:
            return self.reply(405, {"error": "Nur Livestream über diesen Port"})
        path = urlsplit(self.path).path
        if path not in ("/api/tune", "/api/stop", "/api/preset",
                        "/api/remove_preset", "/api/ha_play", "/api/ha_stop"):
            return self.reply(404, {"error": "Unbekannter Pfad"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > 8192:
                return self.reply(413, {"error": "Zu große Anfrage"})
            data = json.loads(self.rfile.read(n)) if n else {}
            if not isinstance(data, dict):
                raise ValueError("Ungültige Anfrage")
            if path == "/api/tune":
                out = radio.tune(data.get("frequency"))
            elif path == "/api/stop":
                radio.stop()
                out = radio.status()
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
            state = radio.status()
            if not state["running"]:
                return self.reply(503, {"error": state["last_error"] or "Empfang nicht aktiv"})
            q = queue.Queue(maxsize=32)
            generation = radio.gen
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
                    if generation != radio.gen or not radio.status()["running"]:
                        break
                try:
                    data = q.get(timeout=2)
                    self.wfile.write(data)
                    self.wfile.flush()
                except queue.Empty:
                    continue
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with radio.lock:
                radio.subscribers.discard(q)


def server(port, public):
    class BoundHandler(Handler):
        public_stream_only = public
    httpd = ThreadingHTTPServer(("0.0.0.0", port), BoundHandler)
    httpd.daemon_threads = True
    print("SDR Radio: " + ("Stream" if public else "Ingress") +
          " läuft auf Port " + str(port), flush=True)
    return httpd


def main():
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
