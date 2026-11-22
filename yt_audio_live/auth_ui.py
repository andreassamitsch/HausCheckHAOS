"""Protected Home Assistant Ingress login page for a real Firefox session.

Credentials are typed only into Google's website in Firefox. The page offers
a remote view of that Firefox process; it never asks for passwords or exports
browser cookies to the client. Only the app extracts its own cookie database.
"""
import asyncio
import json
import logging
import os
import socket
import sqlite3
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from aiohttp import WSMsgType, web

LOG = logging.getLogger("yt_audio_live.auth")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROFILE = Path("/data/ytmusic_auth_browser")
SESSION = Path("/data/ytmusic-session-cookies.txt")
OPTIONS = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
API_KEY = OPTIONS.get("api_key", "")
NOVNC = Path("/usr/share/novnc")
SAVE_LOCK = threading.Lock()

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Music – Anmeldung</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:#111827;color:#f9fafb}
header{padding:16px 20px;background:#1f2937;border-bottom:1px solid #374151}
h1{font-size:20px;margin:0 0 8px}p{font-size:14px;line-height:1.5;margin:8px 0}
main{padding:12px 16px;max-width:1300px;margin:auto}
.actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:12px 0}
button{background:#d43a37;border:0;border-radius:9px;padding:12px 16px;
color:white;font-weight:650;cursor:pointer;min-height:42px}
button.secondary{background:#334155}
button:disabled{opacity:.5;cursor:wait}
#state{margin:6px 0 10px;min-height:22px;font-weight:500}
#screen{width:100%;height:min(70vh,850px);min-height:360px;background:#0b1220;
border:1px solid #475569;border-radius:10px;overflow:hidden}
#screen canvas{max-width:100%;max-height:100%}
small{color:#cbd5e1}
</style></head>
<body><header><h1>🎵 YouTube Music – Google-Anmeldung</h1>
<p>Im Browser unten bei Google anmelden, dann <b>„Sitzung übernehmen“</b> drücken.
Die App übernimmt die YouTube-Cookies automatisch und speichert sie nur in Home Assistant.</p>
<p>Dein Google-Passwort wird nicht an den Musikplayer übertragen. Der Browser läuft in
dieser Home-Assistant-App; schließe die Anmeldung nach dem Speichern.</p></header>
<main>
<div class="actions">
<button id="save">Sitzung übernehmen</button>
<button class="secondary" id="check">Status prüfen</button>
<button class="secondary" id="disconnect">Verbindung trennen</button>
</div><div id="state">Anmeldebrowser wird verbunden …</div>
<div id="screen" aria-label="Google-Anmeldebrowser"></div>
<p><small>Der Browser ist nur über den geschützten Home-Assistant-Ingress erreichbar.
Wenn Google die Anmeldung im Browser ablehnt, wird keine Sitzung übernommen.</small></p>
</main>
<script type="module">
import RFB from "./novnc/core/rfb.js";
const state=document.getElementById("state");
const save=document.getElementById("save");
const check=document.getElementById("check");
const disconnect=document.getElementById("disconnect");
const msg=s=>state.textContent=s;
try{
 const ws=new URL("websockify",window.location.href);
 ws.protocol=location.protocol==="https:"?"wss:":"ws:";
 const rfb=new RFB(document.getElementById("screen"),ws.href);
 rfb.scaleViewport=true;
 rfb.resizeSession=false;
 rfb.viewOnly=false;
 rfb.addEventListener("connect",()=>msg("Browser verbunden. Bitte bei Google anmelden."));
 rfb.addEventListener("disconnect",()=>msg("Browser getrennt. Anmeldeseite erneut öffnen."));
}catch(e){msg("Browser konnte nicht geöffnet werden: "+e.message);}
async function call(url,body){
 const response=await fetch(url,{method:body?"POST":"GET",
  credentials:"same-origin",headers:{"Content-Type":"application/json"},
  ...(body?{body:JSON.stringify(body)}:{})});
 const data=await response.json();
 if(!response.ok)throw new Error(data.error||"HTTP "+response.status);
 return data;
}
async function status(){
 try{const d=await call("api/session");
 msg(d.connected?"YouTube-Music-Sitzung gespeichert – "+(d.playlists_verified?"Playlists bestätigt":"Playlists noch nicht geprüft"):
 "Noch keine gespeicherte Sitzung. Bitte im Browser anmelden.");}
 catch(e){msg("Status: "+e.message)}
}
save.onclick=async()=>{save.disabled=true;msg("YouTube-Cookies werden aus dem Browser übernommen …");
 try{const d=await call("api/session/save",{});
 msg(d.playlists_verified?"Angemeldet! Meine Playlists sind erreichbar.":
 "Cookies gespeichert. Die Playlist-Abfrage konnte noch nicht bestätigt werden.");
 }catch(e){msg("Anmeldung nicht abgeschlossen: "+e.message)}
 finally{save.disabled=false;}};
check.onclick=status;
disconnect.onclick=async()=>{if(!confirm("Gespeicherte App-Sitzung trennen?"))return;
 try{await call("api/session/logout",{});msg("App-Sitzung getrennt.");
 }catch(e){msg("Abmeldung fehlgeschlagen: "+e.message)}};
setTimeout(status,1500);
</script></body></html>"""


def firefox_cookies():
    """Read only YouTube-domain cookies from the real browser's SQLite store."""
    cookie_db = PROFILE / "cookies.sqlite"
    if not cookie_db.is_file():
        raise ValueError("Noch keine Browser-Cookies gefunden. Bitte zuerst anmelden.")
    conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True, timeout=4)
    try:
        rows = conn.execute(
            "SELECT host, path, isSecure, expiry, name, value "
            "FROM moz_cookies WHERE host = 'youtube.com' "
            "OR host = 'music.youtube.com' OR host LIKE '%.youtube.com'"
        ).fetchall()
    finally:
        conn.close()
    now = int(time.time())
    lines = ["# Netscape HTTP Cookie File\n"]
    has_auth = False
    for host, path, secure, expiry, name, value in rows:
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if any(ch in name + value for ch in "\r\n\t"):
            continue
        expiration = int(expiry or 0)
        if expiration and expiration <= now:
            continue
        if name == "__Secure-3PAPISID" and value:
            has_auth = True
        include_subdomains = "TRUE" if host.startswith(".") else "FALSE"
        lines.append("\t".join((host, include_subdomains, path or "/",
                                 "TRUE" if secure else "FALSE",
                                 str(expiration), name, value)) + "\n")
    if not has_auth:
        raise ValueError(
            "Google-Anmeldung noch nicht abgeschlossen "
            "(YouTube-Sitzung fehlt)."
        )
    return "".join(lines)


def reload_music_server():
    request = Request(
        "http://127.0.0.1:8765/api/auth/reload",
        data=b"{}",
        method="POST",
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read(30000))


def save_browser_session():
    raw = firefox_cookies()
    # Validate the cookie file with the exact parser used by the music player.
    from music_catalog import Catalog
    candidate = Catalog(raw)
    # A live library check distinguishes a copied login cookie from
    # a working signed-in YouTube Music session.
    verified = False
    try:
        candidate.library_playlists(limit=1)
        verified = True
    except Exception:
        LOG.warning("session_library_check_not_confirmed")
    temp = SESSION.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        os.chmod(temp, 0o600)
        f.write(raw)
    os.replace(temp, SESSION)
    os.chmod(SESSION, 0o600)
    reload_music_server()
    return {"connected": True, "playlists_verified": verified}


def browser_ready():
    try:
        with socket.create_connection(("127.0.0.1", 5900), timeout=0.8):
            return True
    except OSError:
        return False


async def session_status(request):
    return web.json_response({"connected": SESSION.exists(),
                              "browser_ready": await asyncio.to_thread(browser_ready),
                              "browser_profile_initialized": (PROFILE / "cookies.sqlite").is_file(),
                              "playlists_verified": False})


async def session_save(request):
    if not SAVE_LOCK.acquire(blocking=False):
        return web.json_response({"error": "Anmeldung läuft bereits"}, status=429)
    try:
        result = await asyncio.to_thread(save_browser_session)
        return web.json_response(result)
    except (ValueError, sqlite3.Error) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (OSError, URLError) as exc:
        LOG.warning("session_save_failed reason=%s", type(exc).__name__)
        return web.json_response({"error": "Sitzung konnte nicht gespeichert werden."},
                                 status=503)
    except Exception as exc:
        LOG.error("session_save_failed type=%s", type(exc).__name__)
        return web.json_response({"error": "Google-Sitzung konnte nicht übernommen werden."},
                                 status=502)
    finally:
        SAVE_LOCK.release()


async def session_logout(request):
    if SESSION.exists():
        SESSION.unlink()
    try:
        await asyncio.to_thread(reload_music_server)
    except Exception as exc:
        LOG.warning("session_reload_after_logout_failed %s", type(exc).__name__)
    return web.json_response({"connected": False})


async def browser_socket(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    except OSError:
        await ws.close()
        return ws

    async def forward_tcp():
        try:
            while not ws.closed:
                piece = await reader.read(16384)
                if not piece:
                    break
                await ws.send_bytes(piece)
        except (OSError, ConnectionError, RuntimeError):
            pass

    async def forward_ws():
        try:
            async for message in ws:
                if message.type == WSMsgType.BINARY:
                    writer.write(message.data)
                    await writer.drain()
                elif message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        except (OSError, ConnectionError, RuntimeError):
            pass

    tasks = [asyncio.create_task(forward_tcp()), asyncio.create_task(forward_ws())]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    await ws.close()
    return ws


async def index(request):
    return web.Response(text=PAGE, content_type="text/html",
                        headers={"Cache-Control": "no-store",
                                 "Content-Security-Policy":
                                 "default-src 'self' data: blob:; "
                                 "connect-src 'self' ws: wss:; "
                                 "script-src 'self' 'unsafe-inline'; "
                                 "style-src 'self' 'unsafe-inline'; "
                                 "frame-ancestors 'self'"})


def make_app():
    application = web.Application(client_max_size=2048)
    application.router.add_get("/", index)
    application.router.add_get("/api/session", session_status)
    application.router.add_post("/api/session/save", session_save)
    application.router.add_post("/api/session/logout", session_logout)
    application.router.add_get("/websockify", browser_socket)
    application.router.add_static("/novnc/", str(NOVNC), show_index=False)
    return application


if __name__ == "__main__":
    # No host-port mapping: this server is reachable only via HA Ingress.
    web.run_app(make_app(), host="0.0.0.0", port=8766, access_log=None)
