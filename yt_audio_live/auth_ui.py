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
import shutil
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from aiohttp import WSMsgType, web

LOG = logging.getLogger("yt_audio_live.auth")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROFILE = Path("/data/ytmusic_auth_browser")
SESSION = Path("/data/ytmusic-session-cookies.txt")
SESSION_STATUS = Path("/data/ytmusic-session-status.json")
OPTIONS = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
API_KEY = OPTIONS.get("api_key", "")
NOVNC = Path("/usr/share/novnc")
SAVE_LOCK = threading.Lock()

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,interactive-widget=resizes-content">
<title>YouTube Music – Anmeldung</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:#101828;color:#f8fafc}
header{padding:14px 16px;background:#1c293b;border-bottom:1px solid #344256}
h1{font-size:18px;margin:0 0 4px}
p{font-size:13px;line-height:1.45;margin:5px 0}
main{padding:10px;max-width:1000px;margin:auto}
button{background:#e53935;border:0;border-radius:9px;padding:10px 12px;color:white;font-weight:650;cursor:pointer;min-height:44px;font-size:14px}
button.secondary{background:#36465a}button:disabled{opacity:.48;cursor:wait}
.toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:9;background:#101828;padding:6px 0}
.toolbar button{flex:1 1 auto}
#keyboardbtn{background:#1675b6;flex-grow:2}
#state{min-height:22px;font-size:13px;font-weight:500;margin:7px 3px 9px}
#screen{width:100%;max-width:760px;aspect-ratio:680/900;max-height:78dvh;min-height:360px;background:#111827;border:1px solid #475569;border-radius:10px;overflow:hidden;margin:0 auto;touch-action:auto}
#screen canvas{max-width:100%;max-height:100%}
#keyboardinput{position:fixed;bottom:1px;left:1px;width:2px;height:2px;opacity:.02;z-index:-1;font-size:16px;resize:none}
#keyboardinput:focus{z-index:0}
.bottom-actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 6px}
.bottom-actions button{flex:1 1 140px}
small{color:#cbd5e1;font-size:12px;line-height:1.4}
@media(max-width:650px){
 header{padding:9px 10px}
 header .long{display:none}
 h1{font-size:16px}
 main{padding:5px 8px}
 .toolbar{gap:5px}
 .toolbar button{min-height:42px;padding:7px 8px;font-size:13px}
 #screen{min-height:350px;max-height:78dvh}
}
</style></head>
<body><header><h1>🎵 YouTube Music – Konto verbinden</h1>
<p>Bei Google anmelden, danach unten „Sitzung übernehmen“ wählen.</p>
<p class="long">Der Browser läuft geschützt in Home Assistant. Kein Cookie-Export nötig.</p>
<p><a href="./player" style="color:#b8edff;font-weight:700">🎧 Musik am Handy testen · Ausgabegerät auswählen</a></p></header>
<main>
<div class="toolbar" aria-label="Handy-Browsersteuerung">
  <button id="keyboardbtn" type="button">⌨ Tastatur öffnen</button>
  <button class="secondary" id="enterbtn" type="button">↵ Enter</button>
  <button class="secondary" id="tabbtn" type="button">Tab</button>
  <button class="secondary" id="backbtn" type="button">⌫</button>
  <button class="secondary" id="zoombtn" type="button">🔎 100 %</button>
</div>
<div id="state" role="status" aria-live="polite">Anmeldebrowser wird verbunden …</div>
<div id="screen" aria-label="Interaktiver Google-Anmeldebrowser"></div>
<textarea id="keyboardinput" autocomplete="off" autocapitalize="none"
 autocorrect="off" spellcheck="false" enterkeyhint="done" tabindex="-1"
 aria-label="Android-Tastatur für den Anmeldebrowser"></textarea>
<div class="bottom-actions">
<button id="save" type="button">Sitzung übernehmen</button>
<button class="secondary" id="check" type="button">Status prüfen</button>
<button class="secondary" id="disconnect" type="button">Verbindung trennen</button>
</div>
<p><small>Bedienung: Erst im Google-Feld tippen, dann oben „⌨ Tastatur öffnen“ wählen.
Bei zu kleinen Feldern mit „🔎 100 %“ vergrößern und den Ausschnitt verschieben.
Anmeldedaten bleiben in der Google-Browsersitzung; die App überträgt nur die
Tastatureingaben an den eigenen Browser.</small></p>
</main>
<script type="module">
import RFB from "./novnc/core/rfb.js";
import Keyboard from "./novnc/core/input/keyboard.js";
import KeyTable from "./novnc/core/input/keysym.js";
import keysyms from "./novnc/core/input/keysymdef.js";

const get=id=>document.getElementById(id);
const state=get("state"),save=get("save"),input=get("keyboardinput");
const keyboardbtn=get("keyboardbtn"),zoombtn=get("zoombtn");
const msg=s=>{state.textContent=s;};
let rfb=null,connected=false,zoomed=false;
const BASE_LEN=72;
let previous="";
function resetMobileInput(){
  input.value="_".repeat(BASE_LEN);
  previous=input.value;
  try{input.setSelectionRange(input.value.length,input.value.length);}
  catch(_){}
}
resetMobileInput();

function showKeyboard(){
  if(!connected){msg("Browser noch nicht verbunden.");return;}
  // Focus must happen synchronously in the Android user-click handler.
  input.focus({preventScroll:true});
  try{input.setSelectionRange(input.value.length,input.value.length);}
  catch(_){}
}
function hideKeyboard(){input.blur();}
keyboardbtn.addEventListener("click",()=>{
  if(document.activeElement===input)hideKeyboard();
  else showKeyboard();
});
input.addEventListener("focus",()=>{
  keyboardbtn.textContent="⌨ Tastatur schließen";
  keyboardbtn.setAttribute("aria-pressed","true");
  if(rfb)rfb.focusOnClick=false;
});
input.addEventListener("blur",()=>{
  keyboardbtn.textContent="⌨ Tastatur öffnen";
  keyboardbtn.setAttribute("aria-pressed","false");
  if(rfb)rfb.focusOnClick=true;
  // Do not retain any typed account text in the local keyboard buffer.
  resetMobileInput();
});
const touchKeyboard=new Keyboard(input);
touchKeyboard.onkeyevent=(keysym,code,down)=>{
  if(connected && rfb)rfb.sendKey(keysym,code,down);
};
touchKeyboard.grab();
// noVNC's standard Android IME fallback: many touch keyboards do not emit
// usable keydown codes; translate textarea edits to VNC keysyms instead.
input.addEventListener("input",event=>{
  if(!connected || !rfb){resetMobileInput();return;}
  const updated=event.target.value;
  const old=previous;
  let newLen=updated.length;
  try{newLen=Math.max(event.target.selectionStart,newLen);}catch(_){}
  const oldLen=old.length;
  let chars=newLen-oldLen,backs=chars<0?-chars:0;
  for(let i=0;i<Math.min(oldLen,newLen);i++){
    if(updated.charAt(i)!==old.charAt(i)){
      chars=newLen-i;backs=oldLen-i;break;
    }
  }
  for(let i=0;i<backs;i++)rfb.sendKey(KeyTable.XK_BackSpace,"Backspace");
  for(let i=newLen-chars;i<newLen;i++){
    const sym=keysyms.lookup(updated.charCodeAt(i));
    if(sym!==undefined)rfb.sendKey(sym);
  }
  if(newLen>BASE_LEN*2 || newLen<1){
    resetMobileInput();
  }else{previous=updated;}
});
function sendSpecial(sym,code){
  if(!connected||!rfb)return;
  rfb.sendKey(sym,code);
  if(document.activeElement===input)input.focus({preventScroll:true});
}
get("enterbtn").onclick=()=>sendSpecial(KeyTable.XK_Return,"Enter");
get("tabbtn").onclick=()=>sendSpecial(KeyTable.XK_Tab,"Tab");
get("backbtn").onclick=()=>sendSpecial(KeyTable.XK_BackSpace,"Backspace");
zoombtn.onclick=()=>{
  if(!rfb)return;
  zoomed=!zoomed;
  rfb.scaleViewport=!zoomed;
  rfb.clipViewport=zoomed;
  rfb.dragViewport=zoomed;
  zoombtn.textContent=zoomed?"🔎 Einpassen":"🔎 100 %";
};
try{
  const ws=new URL("websockify",window.location.href);
  ws.protocol=location.protocol==="https:"?"wss:":"ws:";
  rfb=new RFB(get("screen"),ws.href);
  rfb.scaleViewport=true;
  rfb.resizeSession=false;
  rfb.viewOnly=false;
  rfb.addEventListener("connect",()=>{
    connected=true;msg("Browser verbunden. Google-Feld antippen, dann ⌨ öffnen.");
  });
  rfb.addEventListener("disconnect",()=>{
    connected=false;hideKeyboard();msg("Browser getrennt. Anmeldeseite neu öffnen.");
  });
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
 try{
  const d=await call("api/session");
  msg(d.connected?"YouTube-Music-Sitzung gespeichert – "+(d.playlists_verified?"Playlists bestätigt"+(Number.isInteger(d.playlist_count)?" ("+d.playlist_count+")":""):"Playlists noch nicht geprüft"):
  "Noch keine gespeicherte Sitzung. Bitte im Browser anmelden.");
 }catch(e){msg("Status: "+e.message);}
}
save.onclick=async()=>{
 save.disabled=true;hideKeyboard();msg("YouTube-Cookies werden aus dem Browser übernommen …");
 try{
  const d=await call("api/session/save",{});
  msg(d.playlists_verified?"Angemeldet! "+(Number.isInteger(d.playlist_count)?d.playlist_count+" persönliche Playlists erreichbar.":"Meine Playlists sind erreichbar."):
  "Cookies gespeichert. Die Playlist-Abfrage konnte noch nicht bestätigt werden.");
 }catch(e){msg("Anmeldung nicht abgeschlossen: "+e.message);}
 finally{save.disabled=false;}
};
get("check").onclick=status;
get("disconnect").onclick=async()=>{
 if(!confirm("Gespeicherte App-Sitzung trennen?"))return;
 try{await call("api/session/logout",{});msg("App-Sitzung getrennt.");}
 catch(e){msg("Abmeldung fehlgeschlagen: "+e.message);}
};
setTimeout(status,1500);
</script></body></html>"""


def _query_youtube_cookies(cookie_db, timeout=0.5):
    """Query only YouTube cookie rows. The values never leave this process."""
    conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True, timeout=timeout)
    try:
        return conn.execute(
            "SELECT host, path, isSecure, expiry, name, value "
            "FROM moz_cookies WHERE host = 'youtube.com' "
            "OR host = 'music.youtube.com' OR host LIKE '%.youtube.com'"
        ).fetchall()
    finally:
        conn.close()


def _snapshot_youtube_cookies(cookie_db):
    """Read from a *private* disposable copy when Firefox holds SQLite locks.

    Firefox may keep cookies.sqlite in exclusive WAL mode. A regular read-only
    connection against its live DB then fails with 'database is locked'.
    Copy the main DB with its WAL and SHM sidecars to a private directory,
    query that snapshot, and securely dispose of it. Never edit Firefox's DB.
    A concurrent WAL checkpoint can invalidate a copy; retry in that case.
    """
    last_error = None
    for attempt in range(6):
        with tempfile.TemporaryDirectory(prefix=".ytmusic-cookie-snapshot-",
                                         dir="/data") as folder:
            snapshot = Path(folder) / "cookies.sqlite"
            try:
                shutil.copyfile(cookie_db, snapshot)
                os.chmod(snapshot, 0o600)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(cookie_db) + suffix)
                    if sidecar.exists():
                        copied = Path(str(snapshot) + suffix)
                        shutil.copyfile(sidecar, copied)
                        os.chmod(copied, 0o600)
                rows = _query_youtube_cookies(snapshot)
                LOG.info("browser_cookies_read_via_private_snapshot")
                return rows
            except (sqlite3.Error, OSError) as exc:
                last_error = exc
        # Retry: Firefox may have checkpointed its WAL during the copy.
        time.sleep(0.15 * (attempt + 1))
    raise sqlite3.OperationalError(
        "Firefox-Cookies konnten nicht sicher gelesen werden. "
        "Bitte die Sitzung erneut übernehmen."
    ) from last_error


def firefox_cookies():
    """Read YouTube cookies without modifying or closing the Firefox session."""
    cookie_db = PROFILE / "cookies.sqlite"
    if not cookie_db.is_file():
        raise ValueError("Noch keine Browser-Cookies gefunden. Bitte zuerst anmelden.")
    try:
        rows = _query_youtube_cookies(cookie_db)
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
            raise
        rows = _snapshot_youtube_cookies(cookie_db)
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
    playlist_count = None
    try:
        playlists = candidate.library_playlists(limit=100)
        verified = isinstance(playlists, list)
        playlist_count = len(playlists) if verified else None
    except Exception:
        LOG.warning("session_library_check_not_confirmed")
    temp = SESSION.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        os.chmod(temp, 0o600)
        f.write(raw)
    os.replace(temp, SESSION)
    os.chmod(SESSION, 0o600)
    reload_music_server()
    status = {"connected": True, "playlists_verified": verified,
              "playlist_count": playlist_count}
    temporary_status = SESSION_STATUS.with_suffix(".tmp")
    with open(temporary_status, "w", encoding="utf-8") as handle:
        os.chmod(temporary_status, 0o600)
        json.dump(status, handle)
    os.replace(temporary_status, SESSION_STATUS)
    os.chmod(SESSION_STATUS, 0o600)
    return status


def browser_ready():
    try:
        with socket.create_connection(("127.0.0.1", 5900), timeout=0.8):
            return True
    except OSError:
        return False


async def session_status(request):
    connected = SESSION.exists()
    status = {}
    if connected and SESSION_STATUS.is_file():
        try:
            status = json.loads(SESSION_STATUS.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            LOG.warning("session_status_cache_unreadable")
    return web.json_response({
        "connected": connected,
        "browser_ready": await asyncio.to_thread(browser_ready),
        "browser_profile_initialized": (PROFILE / "cookies.sqlite").is_file(),
        "playlists_verified": bool(connected and status.get("playlists_verified")),
        "playlist_count": status.get("playlist_count") if connected else None,
    })


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
    if SESSION_STATUS.exists():
        SESSION_STATUS.unlink()
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
    from mobile_preview import routes as register_mobile_routes
    register_mobile_routes(application)
    return application


if __name__ == "__main__":
    # No host-port mapping: this server is reachable only via HA Ingress.
    web.run_app(make_app(), host="0.0.0.0", port=8766, access_log=None)
