"""Ingress-only prototype; Codex signalling based on Synero/hermes-live-voice.
See LICENSE and NOTICE.md. No API-key fallback. No public listener mapping.
"""
import collections
import json
import os
import pathlib
import pwd
import queue
import re
import secrets
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

VOICES = frozenset("cove juniper maple spruce ember vale breeze arbor sol sonna".split())
PERSONA = ("Du bist die Live-Stimme des Hausassistenten. Sprich natürliches, zügiges Deutsch "
           "und antworte kurz. Grüße und Smalltalk beantwortest du selbst. Delegiere sämtliche "
           "Haussteuerung, aktuelle Hausdaten und komplexe Aufgaben an den vorhandenen Agenten. "
           "Bei Unklarheit frage nach. Erfinde keine Aktionen oder Ergebnisse. Warte auf das "
           "tatsächliche Resultat und sprich es verständlich. Bei Gesprächsende verabschiede dich kurz.")
NO_TOOLS = ("Client-managed handoffs only. Never run tools, read files, run commands or "
            "perform delegated work in this Codex thread. Reply only skip.")
HOME = pathlib.Path("/data/codex")
ALLOWED_PEER = "172.30.32.2"
OPTIONS = {}
TOKEN = ""
CSRF = collections.OrderedDict()
LOCK = threading.RLock()
ACTIVE = None
LOGIN = None
LOGIN_CODE = None
RPC = None
WARM = None
WARM_WAKE = threading.Event()
SIGNED_CACHE = (0.0, False)

def payload_for(text, agent, conversation=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("Ungültige Anfrage")
    if not re.fullmatch(r"conversation\.[a-z0-9_]+", agent):
        raise ValueError("Ungültiger Agent")
    data = {"text": text.strip(), "language": "de", "agent_id": agent}
    if conversation:
        data["conversation_id"] = conversation
    return data

def unpack_response(data):
    response = data.get("response") or {}
    speech = ((response.get("speech") or {}).get("plain") or {}).get("speech")
    if not isinstance(speech, str) or not speech.strip():
        raise ValueError("Keine Textantwort des Hausassistenten")
    return {"text": speech[:8000], "conversation_id": data.get("conversation_id"),
            "continue_conversation": bool(data.get("continue_conversation")),
            "response_type": response.get("response_type")}

def is_admin_record(user, user_id):
    return (user.get("id") == user_id and user.get("is_active") is True
            and not user.get("system_generated")
            and (user.get("is_owner") is True or "system-admin" in (user.get("group_ids") or [])))


def ingress_admin(user_id):
    # The Core API token is privileged: never expose it to browsers or non-admin users.
    # Check the actual Ingress user's current group membership, fail closed.
    import websocket
    ws = None
    try:
        ws = websocket.create_connection("ws://supervisor/core/websocket", timeout=5)
        if json.loads(ws.recv()).get("type") != "auth_required":
            return False
        ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        if json.loads(ws.recv()).get("type") != "auth_ok":
            return False
        ws.send(json.dumps({"id": 1, "type": "config/auth/list"}))
        result = json.loads(ws.recv())
        return result.get("success") is True and any(
            is_admin_record(user, user_id) for user in result.get("result", []))
    except Exception:
        return False
    finally:
        if ws is not None:
            ws.close()


def child_env():
    # Do not inherit Supervisor token, API keys or arbitrary provider settings.
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(HOME),
            "CODEX_HOME": str(HOME), "LANG": "C.UTF-8", "TERM": "dumb"}

def spawn(args, **kw):
    user = pwd.getpwnam("ha_voice")
    return subprocess.Popen(["codex", *args], env=child_env(), cwd="/tmp",
                            user=user.pw_uid, group=user.pw_gid, extra_groups=[], **kw)

def signed_in():
    global SIGNED_CACHE
    checked, value = SIGNED_CACHE
    now = time.monotonic()
    if checked and now - checked < (30 if value else 5):
        return value
    p = spawn(["login", "status"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        out, _ = p.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        SIGNED_CACHE = (time.monotonic(), False)
        return False
    value = p.returncode == 0 and "chatgpt" in out.lower()
    SIGNED_CACHE = (time.monotonic(), value)
    return value

class Broker:
    def __init__(self):
        self.proc = spawn(["app-server", "--listen", "stdio://", "--enable", "realtime_conversation",
                           "-c", "model_provider=openai", "-c", "approval_policy=never",
                           "-c", "sandbox_mode=read-only", "-c", "suppress_unstable_features_warning=true"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, bufsize=1)
        self.seq = 0
        self.incoming = queue.Queue()
        self.events = collections.deque(maxlen=2000)
        threading.Thread(target=self.read, daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": "ha-live-voice", "version": "0.1.6"},
                                     "capabilities": {"experimentalApi": True}})
        except Exception:
            self.close()
            raise

    def read(self):
        for line in self.proc.stdout:
            try:
                self.incoming.put(json.loads(line))
            except ValueError:
                pass
        self.incoming.put(None)

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + "\n")
        self.proc.stdin.flush()

    def receive(self, end):
        left = end - time.monotonic()
        if left <= 0:
            raise TimeoutError("Zeitlimit")
        try:
            item = self.incoming.get(timeout=left)
        except queue.Empty:
            raise TimeoutError("Zeitlimit") from None
        if item is None:
            raise RuntimeError("Codex beendet")
        if "method" in item and "id" in item:
            # Reject any server request (approvals etc.); this lane does not run tools.
            self.send({"jsonrpc": "2.0", "id": item["id"],
                       "error": {"code": -32601, "message": "Not allowed in voice-only broker"}})
            return {}
        return item

    def call(self, method, params, timeout=25):
        self.seq += 1
        rid = self.seq
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        end = time.monotonic() + timeout
        while True:
            msg = self.receive(end)
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError("Codex RPC abgelehnt: " + method)
                return msg.get("result") or {}
            self.events.append(msg)

    def start(self, offer, voice):
        thread = self.call("thread/start", {"cwd": "/tmp", "modelProvider": "openai",
                                           "approvalPolicy": "never", "sandbox": "read-only"})
        tid = thread["thread"]["id"]
        self.events.clear()
        self.call("thread/realtime/start", {
            "threadId": tid, "transport": {"type": "webrtc", "sdp": offer},
            "outputModality": "audio", "version": "v3", "voice": voice, "prompt": PERSONA,
            "realtimeStartInstructions": NO_TOOLS, "clientManagedHandoffs": True,
            "delegationAckFiller": True})
        end = time.monotonic() + 45
        while True:
            event = self.events.popleft() if self.events else self.receive(end)
            if event.get("method") == "thread/realtime/error":
                raise RuntimeError("Live-Sitzung abgelehnt (Kontingent oder Versionskompatibilität prüfen)")
            if event.get("method") == "thread/realtime/sdp":
                p = event.get("params") or {}
                if p.get("sdp"):
                    return tid, p["sdp"]

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

def drop_warm():
    global WARM
    if WARM is not None:
        WARM.close()
        WARM = None

def take_broker():
    global WARM
    broker, WARM = WARM, None
    if broker is not None:
        if broker.proc.poll() is None:
            return broker
        broker.close()
    return Broker()

def maintain_warm():
    # Only initialize the local process, never start a voice thread or media session here.
    global WARM
    while True:
        try:
            with LOCK:
                if ACTIVE is None and (LOGIN is None or LOGIN.poll() is not None):
                    if not signed_in():
                        drop_warm()
                    elif WARM is None or WARM.proc.poll() is not None:
                        drop_warm()
                        WARM = Broker()
                        print("Codex voice broker ready (no realtime session)", flush=True)
        except Exception as exc:
            print("Broker preparation failed:", type(exc).__name__, flush=True)
        WARM_WAKE.wait(3)
        WARM_WAKE.clear()

def stop():
    global ACTIVE, RPC
    if RPC is not None:
        RPC.close()
    ACTIVE = RPC = None
    WARM_WAKE.set()

def expire():
    while True:
        time.sleep(5)
        with LOCK:
            if ACTIVE and time.monotonic() - ACTIVE["seen"] > 90:
                stop()

def read_login(proc):
    global LOGIN_CODE, SIGNED_CACHE
    for line in proc.stdout:
        match = re.search(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,5}\b", re.sub(r"\x1b\[[0-9;]*m", "", line))
        if match:
            LOGIN_CODE = match.group()
    proc.wait()
    with LOCK:
        LOGIN_CODE = None
        SIGNED_CACHE = (0.0, False)
    WARM_WAKE.set()

def delegate(text, conversation):
    data = payload_for(text, OPTIONS["agent_id"], conversation)
    req = urllib.request.Request("http://supervisor/core/api/conversation/process",
                                 data=json.dumps(data).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + TOKEN,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as result:
        return unpack_response(json.load(result))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log tokens, SDP, device codes, or household requests.

    def respond(self, status, value, mime="application/json"):
        raw = json.dumps(value, ensure_ascii=False).encode() if mime == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def user(self):
        if self.client_address[0] != ALLOWED_PEER:
            return None
        user = self.headers.get("X-Remote-User-Id")
        return user if user and ingress_admin(user) else None

    def do_GET(self):
        user = self.user()
        if not user:
            return self.respond(403, {"error": "Nur über Home Assistant Ingress"})
        path = urlsplit(self.path).path
        if path in ("/", ""):
            return self.respond(200, pathlib.Path("index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/app.js":
            return self.respond(200, pathlib.Path("app.js").read_bytes(), "text/javascript; charset=utf-8")
        if path == "/capture-worklet.js":
            return self.respond(200, pathlib.Path("capture-worklet.js").read_bytes(), "text/javascript; charset=utf-8")
        if path == "/api/status":
            with LOCK:
                key = secrets.token_urlsafe(32)
                CSRF[key] = (user, time.monotonic() + 3600)
                while len(CSRF) > 256:
                    CSRF.popitem(last=False)
                return self.respond(200, {"csrf": key, "signed_in": signed_in(),
                                          "voice": OPTIONS["voice"], "idle_seconds": OPTIONS["idle_seconds"],
                                          "login_code": LOGIN_CODE})
        return self.respond(404, {"error": "Nicht gefunden"})

    def do_POST(self):
        global ACTIVE, RPC, LOGIN, LOGIN_CODE, SIGNED_CACHE
        user = self.user()
        key = self.headers.get("X-Voice-CSRF", "")
        grant = CSRF.get(key)
        if not user or not grant or grant[0] != user or grant[1] < time.monotonic():
            return self.respond(403, {"error": "Sitzung abgelaufen"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100000 or not self.headers.get("Content-Type", "").startswith("application/json"):
                return self.respond(400, {"error": "Ungültige Daten"})
            body = json.loads(self.rfile.read(size))
            path = urlsplit(self.path).path
            with LOCK:
                if path == "/api/login":
                    if ACTIVE:
                        raise ValueError("Zuerst Gespräch beenden")
                    if LOGIN is None or LOGIN.poll() is not None:
                        LOGIN_CODE = None
                        SIGNED_CACHE = (0.0, False)
                        drop_warm()
                        LOGIN = spawn(["login", "--device-auth"], stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, bufsize=1)
                        threading.Thread(target=read_login, args=(LOGIN,), daemon=True).start()
                    return self.respond(200, {"ok": True})
                if path == "/api/start":
                    if ACTIVE:
                        raise ValueError("Es läuft bereits ein Gespräch")
                    if not signed_in():
                        raise ValueError("Zuerst mit ChatGPT anmelden")
                    offer = body.get("offer")
                    voice = body.get("voice", OPTIONS["voice"])
                    if not isinstance(offer, str) or not offer.startswith("v=0") or voice not in VOICES:
                        raise ValueError("Ungültiger WebRTC-Offer oder Stimme")
                    try:
                        RPC = take_broker()
                        tid, answer = RPC.start(offer, voice)
                        ACTIVE = {"id": secrets.token_urlsafe(24), "user": user, "thread": tid,
                                  "seen": time.monotonic(), "conversation": None, "requests": {}}
                    except Exception:
                        stop()
                        raise
                    return self.respond(200, {"id": ACTIVE["id"], "answer": answer})
                if not ACTIVE or ACTIVE["user"] != user or ACTIVE["id"] != body.get("id"):
                    raise ValueError("Keine passende Live-Sitzung")
                ACTIVE["seen"] = time.monotonic()
                if path == "/api/stop":
                    stop()
                    return self.respond(200, {"ok": True})
                if path == "/api/ping":
                    return self.respond(200, {"ok": True})
                if path == "/api/interrupt":
                    turn = body.get("turn")
                    if not isinstance(turn, str) or not turn or len(turn) > 256:
                        raise ValueError("Ungültiger Turn")
                    RPC.call("turn/interrupt", {"threadId": ACTIVE["thread"], "turnId": turn}, timeout=8)
                    return self.respond(200, {"ok": True})
                if path == "/api/delegate":
                    item = body.get("item")
                    if not isinstance(item, str) or not 0 < len(item) <= 256:
                        raise ValueError("Ungültige Delegation")
                    cached = ACTIVE["requests"].get(item)
                    if cached is not None:
                        return self.respond(200, cached)
                    if len(ACTIVE["requests"]) >= 100:
                        raise ValueError("Gesprächslimit erreicht")
                    # Record before executing; never replay an uncertain device action.
                    ACTIVE["requests"][item] = {"text": "Ausgang der Anfrage nicht bestätigt. Nicht automatisch wiederholen."}
                    result = delegate(body.get("text"), ACTIVE["conversation"])
                    ACTIVE["conversation"] = result.get("conversation_id") or ACTIVE["conversation"]
                    ACTIVE["requests"][item] = result
                    return self.respond(200, result)
                return self.respond(404, {"error": "Nicht gefunden"})
        except ValueError as exc:
            return self.respond(400, {"error": str(exc)[:200]})
        except Exception as exc:
            # Never forward raw upstream errors; they can include private input or credentials.
            print("Request failed:", type(exc).__name__, flush=True)
            return self.respond(502, {"error": "Anfrage fehlgeschlagen. Keine automatische Wiederholung."})

def main():
    global OPTIONS, TOKEN
    OPTIONS = json.loads(pathlib.Path("/data/options.json").read_text())
    TOKEN = os.environ["SUPERVISOR_TOKEN"]
    HOME.mkdir(mode=0o700, exist_ok=True)
    user = pwd.getpwnam("ha_voice")
    os.chown(HOME, user.pw_uid, user.pw_gid)
    HOME.chmod(0o700)
    threading.Thread(target=expire, daemon=True).start()
    threading.Thread(target=maintain_warm, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()

if __name__ == "__main__":
    main()
