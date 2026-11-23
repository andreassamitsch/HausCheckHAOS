"""Mobile YouTube Music preview over authenticated Home Assistant Ingress.

Read-only metadata and audio probes never call HA media services. Browser
preview is streamed to the requesting phone only; remote players require a
separate explicit UI consent and double confirmation.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, web

LOG = logging.getLogger("yt_audio_live.mobile")
OPTS = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
API_KEY = OPTS["api_key"]
BASE_URL = str(OPTS["stream_base_url"]).rstrip("/")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TRACKS_VERIFIED = {}
PLAY_MEDIA = 131072

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube Music · Sicherer Handy-Test</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif}
*{box-sizing:border-box}
body{background:#0d1929;color:#f8fafc;margin:0}
header{padding:17px 16px 13px;background:linear-gradient(130deg,#0c82ac,#114469)}
h1{margin:0 0 6px;font-size:21px}
.subtitle{font-size:13px;opacity:.9;margin:0}
main{max-width:790px;margin:auto;padding:14px}
.panel{background:#16273b;border:1px solid #30455b;border-radius:15px;padding:14px;margin-bottom:14px}
h2{font-size:16px;margin:0 0 12px}
label{display:block;font-size:13px;font-weight:650;margin:7px 0}
button,select,input{font:inherit;min-height:44px;border-radius:9px}
button{border:0;padding:10px 14px;font-weight:650;background:#008fc1;color:#fff;cursor:pointer}
button:disabled{opacity:.42;cursor:default}
button.secondary{background:#344961}
select,input[type=text]{border:1px solid #64758b;background:#0b1d31;color:white;padding:9px;width:100%}
input[type=checkbox]{width:20px;height:20px;min-height:auto;accent-color:#00a8e7}
.safeline{display:flex;align-items:flex-start;gap:10px;font-size:13px;margin-top:9px;line-height:1.4}
.grid{display:flex;gap:8px}
.grid>*{flex:1;min-width:0}
#results{max-height:42vh;overflow:auto}
.track{display:flex;gap:10px;align-items:center;width:100%;text-align:left;background:#21364c;margin:5px 0;padding:7px}
.track img{height:49px;width:49px;object-fit:cover;border-radius:6px}
.track span{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis}
.track strong{font-size:14px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track small{font-size:12px;opacity:.75;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track[aria-pressed=true]{outline:2px solid #4fd2ff}
.coverrow{display:flex;gap:12px;align-items:center}
#cover{height:90px;width:90px;object-fit:cover;border-radius:12px;background:#28445d}
#song{font-size:17px;font-weight:750;overflow-wrap:anywhere}
#artist{font-size:13px;color:#c6d8e8;margin:5px 0}
#message{font-size:13px;white-space:pre-wrap;line-height:1.45;min-height:20px;margin:9px 0}
audio{width:100%;margin:10px 0 2px}
.note{font-size:12px;color:#c1d3e3;line-height:1.4;margin-top:9px}
#remoteGate{display:none}
a{color:#a8e5ff}
@media(max-width:450px){main{padding:10px}.panel{padding:11px}.grid{gap:6px}.grid button{padding:10px 7px;font-size:13px}}
</style></head>
<body>
<header><h1>🎵 YouTube Music Live</h1>
<p class="subtitle">Handy-Test · sichere Wiedergabe mit Geräteauswahl</p></header>
<main>
<section class="panel">
<h2>Ausgabegerät</h2>
<label for="output">Wo soll Musik abgespielt werden?</label>
<select id="output"><option value="phone">📱 Dieses Handy (Standard)</option></select>
<div id="remoteGate" class="safeline">
 <input id="remoteConsent" type="checkbox">
 <label for="remoteConsent">Ich möchte die Wiedergabe auf diesem Lautsprecher im Haus ausdrücklich freigeben.</label>
</div>
<p class="note">Ein Gerätewechsel startet keine Wiedergabe. Die Soundbar wird niemals automatisch ausgewählt oder angesteuert.</p>
</section>
<section class="panel">
<h2>Musik auswählen</h2>
<label for="library">Meine Playlists</label>
<select id="library"><option value="">Playlist auswählen …</option></select>
<label for="search">Oder einen Titel suchen</label>
<div class="grid"><input id="search" type="text" placeholder="Künstler, Titel, Playlist …" autocomplete="off">
<button id="searchBtn">Suchen</button></div>
<select id="searchKind" style="width:100%;margin-top:7px">
<option value="songs">Songs</option><option value="playlists">Playlists</option>
<option value="radios">Radios nach Künstler/Titel</option>
<option value="featured_playlists">YouTube-Mixes</option>
<option value="community_playlists">Community-Playlists</option>
</select>
<div class="grid" style="margin-top:8px">
<button id="shuffle" class="secondary">🔀 Shuffle: Aus</button>
<button id="repeat" class="secondary">🔁 Repeat: Aus</button>
<button id="radio" class="secondary" disabled>📻 Radio</button>
</div>
<div class="grid" style="margin-top:7px"><button id="autoContinue" class="secondary" aria-pressed="true">∞ Automatisch fortsetzen: An</button></div>
<div id="results" aria-label="Titel"></div>
</section>
<section class="panel">
<h2>Ausgewählter Titel</h2>
<div class="coverrow"><img id="cover" alt="" src="" style="visibility:hidden">
<div><div id="song">Noch kein Titel ausgewählt</div><div id="artist">–</div></div></div>
<p id="message" role="status" aria-live="polite">Bereit. Bisher wurde nichts abgespielt.</p>
<div class="grid">
<button id="probe" class="secondary" disabled>Audioquelle prüfen</button>
<button id="play" disabled>▶ Abspielen</button>
</div>
<audio id="audio" controls preload="none" hidden></audio>
<p class="note">„Audioquelle prüfen“ überträgt höchstens einen kleinen Datenblock und startet keinen Lautsprecher.
Nur „Abspielen“ kann Ton ausgeben – auf dem ausdrücklich ausgewählten Gerät.</p>
</section>
<p class="note"><a href="./">Zurück zur Google-Anmeldung</a></p>
</main>
<script>
const $=id=>document.getElementById(id);
let selected=null,verified=false,outputs=new Map(),playingRemote="";
let trackQueue=[],shuffle=false,repeatMode="off",radioMode=false;
let autoContinue=true,playedInCycle=new Set();
const audio=$("audio"),out=$("output"),msg=s=>$("message").textContent=s;
async function api(path,body){
 const headers={"Content-Type":"application/json"};
 if(body)headers["X-HausCheck-Intent"]="explicit-remote-playback";
 const r=await fetch("api/mobile/"+path,{credentials:"same-origin",cache:"no-store",
  method:body?"POST":"GET",headers,...(body?{body:JSON.stringify(body)}:{})});
 const d=await r.json();
 if(!r.ok)throw Error(d.error||"HTTP "+r.status);
 return d;
}
function resetOutput(){
 audio.pause();audio.removeAttribute("src");audio.load();audio.hidden=true;
 verified=false;$("play").disabled=true;$("remoteConsent").checked=false;
 $("remoteGate").style.display=out.value==="phone"?"none":"flex";
 $("play").textContent=out.value==="phone"?"▶ Auf diesem Handy abspielen":"▶ Auf ausgewähltem Gerät abspielen";
 msg(selected?"Ausgabe geändert. Zuerst Audioquelle erneut prüfen.":"Ausgabegerät ausgewählt. Noch keine Wiedergabe.");
}
out.onchange=resetOutput;
function choose(t){
 if(!t?.video_id || !/^[A-Za-z0-9_-]{11}$/.test(t.video_id))return;
 selected=t;playedInCycle.add(t.video_id);
 resetOutput();$("probe").disabled=false;$("radio").disabled=false;
 $("song").textContent=t.title||"Unbekannter Titel";$("artist").textContent=t.artist||"";
 $("cover").style.visibility="visible";
 $("cover").src=(typeof t.thumbnail==="string"&&t.thumbnail.startsWith("https://"))?t.thumbnail:"";
 msg("Titel ausgewählt. Keine Wiedergabe gestartet.");
 document.querySelectorAll(".track").forEach(e=>e.setAttribute("aria-pressed",String(e.dataset.id===t.video_id)));
}
function listTracks(items,kind="songs"){
 const wrap=$("results");wrap.replaceChildren();
 trackQueue=kind.includes("playlist")?[]:items.filter(t=>t?.video_id);
 playedInCycle.clear();
 radioMode=kind==="radios";
 if(!items.length){wrap.textContent="Keine abspielbaren Titel gefunden.";return;}
 for(const t of items.slice(0,100)){
  if(!t.video_id&&!t.playlist_id)continue;
  const button=document.createElement("button");button.className="track";
  button.type="button";button.dataset.id=t.video_id||t.playlist_id;
  const img=document.createElement("img");img.alt="";img.loading="lazy";
  if(typeof t.thumbnail==="string" && t.thumbnail.startsWith("https://"))img.src=t.thumbnail;
  const span=document.createElement("span"),title=document.createElement("strong"),artist=document.createElement("small");
  title.textContent=t.title||t.video_id||t.playlist_id;
  artist.textContent=t.artist||(t.playlist_id?"Playlist":kind==="radios"?"Radio":"");
  span.append(title,artist);button.append(img,span);
  button.onclick=()=>t.playlist_id?loadPlaylist(t.playlist_id):choose(t);
  wrap.append(button);
 }
}
$("searchBtn").onclick=async()=>{
 const q=$("search").value.trim();if(!q)return;
 msg("Suche …");
 try{
  const kind=$("searchKind").value;
  const d=await api("search?q="+encodeURIComponent(q)+"&kind="+kind);
  listTracks(d.results||[],kind);
  msg((d.results||[]).length+" Treffer gefunden.");
 }
 catch(e){msg("Suche fehlgeschlagen: "+e.message)}
};
$("search").onkeydown=e=>{if(e.key==="Enter")$("searchBtn").click()};
async function loadPlaylist(id){
 if(!id)return;
 msg("Playlist wird geladen …");
 try{
  const d=await api("playlist?id="+encodeURIComponent(id));
  listTracks(d.tracks||[]);
  msg((d.tracks||[]).length+" Titel in "+d.title+" geladen.");
 }catch(e){msg("Playlist konnte nicht geladen werden: "+e.message);}
}
$("library").onchange=()=>loadPlaylist($("library").value);
$("shuffle").onclick=()=>{
 shuffle=!shuffle;$("shuffle").textContent="🔀 Shuffle: "+(shuffle?"An":"Aus");
};
$("repeat").onclick=()=>{
 repeatMode=repeatMode==="off"?"all":repeatMode==="all"?"one":"off";
 $("repeat").textContent="🔁 Repeat: "+(repeatMode==="off"?"Aus":repeatMode==="one"?"Titel":"Alle");
};
function showAutoContinue(){
 $("autoContinue").textContent="∞ Automatisch fortsetzen: "+(autoContinue?"An":"Aus");
 $("autoContinue").setAttribute("aria-pressed",String(autoContinue));
}
async function refreshAutoContinue(){
 try{
  const d=await api("settings");
  autoContinue=d.auto_continue_enabled!==false;
  showAutoContinue();
 }catch(_){}
}
$("autoContinue").onclick=async()=>{
 const button=$("autoContinue");button.disabled=true;
 try{
  const d=await api("settings",{enabled:!autoContinue});
  autoContinue=d.auto_continue_enabled!==false;
  showAutoContinue();
  msg("Automatisch fortsetzen: "+(autoContinue?"Ein":"Aus")+". Keine Wiedergabe gestartet.");
 }catch(e){msg("Einstellung konnte nicht gespeichert werden: "+e.message);}
 finally{button.disabled=false;}
};
$("radio").onclick=async()=>{
 if(!selected)return;
 msg("Radio wird vorbereitet (ohne Wiedergabe) …");
 try{
  const d=await api("radio?video_id="+encodeURIComponent(selected.video_id));
  trackQueue=[selected,...(d.tracks||[])].filter(t=>t?.video_id);
  radioMode=true;
  msg("Radio vorbereitet: "+trackQueue.length+" Titel. ▶ startet nur auf dem gewählten Gerät.");
 }catch(e){msg("Radio konnte nicht vorbereitet werden: "+e.message);}
};
$("probe").onclick=async()=>{
 if(!selected)return;
 $("probe").disabled=true;$("play").disabled=true;verified=false;
 msg("Prüfe Audioquelle, ohne etwas abzuspielen …");
 try{
  const d=await api("probe?video_id="+encodeURIComponent(selected.video_id));
  if(!d.ok)throw Error(d.reason||"Audioquelle nicht erreichbar");
  verified=true;$("play").disabled=false;
  msg("Audioquelle verfügbar. Jetzt kannst du ausdrücklich die Wiedergabe starten.");
 }catch(e){msg("Audioquelle nicht verfügbar: "+e.message)}
 finally{$("probe").disabled=false}
};
$("play").onclick=async()=>{
 if(!selected||!verified)return;
 const id=selected.video_id;
 if(out.value==="phone"){
  audio.hidden=false;
  audio.src="api/mobile/audio/"+encodeURIComponent(id);
  // Called synchronously in the actual button gesture, not in a background task.
  msg("Starte Wiedergabe ausschließlich auf diesem Handy …");
  try{await audio.play();}catch(e){msg("Handy konnte nicht starten: "+e.message);}
  return;
 }
 if(!$("remoteConsent").checked){msg("Bitte zuerst den Lautsprecher ausdrücklich freigeben.");return;}
 const name=outputs.get(out.value)||out.value;
 if(!window.confirm("ACHTUNG: Jetzt Musik auf „"+name+"“ IM HAUS abspielen?"))return;
 try{
  const data=await api("remote",{video_id:id,entity_id:out.value,
   confirmed_remote:true});
  playingRemote=data.entity_id;
  msg("Wiedergabe auf „"+name+"“ ausdrücklich gestartet. Die Lautstärke wurde nicht verändert.");
 }catch(e){msg("Lautsprecher konnte nicht starten: "+e.message)}
};
audio.addEventListener("error",()=>msg("Der Audiostream konnte am Handy nicht abgespielt werden."));
async function advancePhone(){
 // Automatic follow-up ONLY for a user-started phone audio session.
 // There is NO call to /api/mobile/remote or media_player.play_media here.
 if(out.value!=="phone" || !selected)return;
 let next=null;
 if(repeatMode==="one")next=selected;
 else if(trackQueue.length){
  if(shuffle){
   let choices=trackQueue.filter(t=>!playedInCycle.has(t.video_id));
   if(!choices.length&&repeatMode==="all"){
    playedInCycle.clear();
    choices=trackQueue;
   }
   if(choices.length)next=choices[Math.floor(Math.random()*choices.length)];
  }else{
   const idx=trackQueue.findIndex(t=>t.video_id===selected.video_id);
   next=trackQueue[idx+1]||null;
   if(!next&&repeatMode==="all")next=trackQueue[0];
  }
 }
 if(!next&&repeatMode==="off"&&(radioMode||autoContinue)){
  try{
   const d=await api("radio?video_id="+encodeURIComponent(selected.video_id));
   const known=new Set(trackQueue.map(t=>t.video_id));known.add(selected.video_id);
   const more=(d.tracks||[]).filter(t=>t?.video_id&&!known.has(t.video_id));
   trackQueue.push(...more);
   next=more[0]||null;
  }catch(e){msg("Ähnliche Titel konnten nicht geladen werden.");}
 }
 if(!next){msg("Wiedergabe beendet. Automatisch fortsetzen: "+(autoContinue?"An":"Aus"));return;}
 try{
  const check=await api("probe?video_id="+encodeURIComponent(next.video_id));
  if(!check.ok)throw Error(check.reason||"Audio nicht verfügbar");
  if(out.value!=="phone"||!selected)return;
  selected=next;playedInCycle.add(next.video_id);verified=true;
  $("song").textContent=next.title||"Titel";$("artist").textContent=next.artist||"";
  $("cover").src=next.thumbnail||"";$("cover").style.visibility="visible";
  audio.hidden=false;audio.src="api/mobile/audio/"+encodeURIComponent(next.video_id);
  await audio.play();
 }catch(e){msg("Automatische Fortsetzung fehlgeschlagen: "+e.message);}
}
audio.addEventListener("ended",()=>{void advancePhone();});
(async()=>{
 try{
  const devices=await api("outputs");
  for(const p of devices.outputs||[]){
   outputs.set(p.entity_id,p.name);
   const op=document.createElement("option");op.value=p.entity_id;op.textContent="🔊 "+p.name;
   out.append(op);
  }
  // Always default to the current browser – NEVER inherit HA soundbar.
  out.value="phone";
  await refreshAutoContinue();
  const lib=await api("library");
  for(const p of (lib.playlists||[])){
   const op=document.createElement("option");op.value=p.playlist_id;op.textContent=p.title;
   $("library").append(op);
  }
  msg("Angemeldet. "+(lib.playlists||[]).length+" Playlists verfügbar. Noch keine Wiedergabe.");
 }catch(e){msg("Initialisierung: "+e.message)}
})();
setInterval(()=>{if(document.visibilityState==="visible")void refreshAutoContinue();},12000);
</script></body></html>"""


def safe_video_id(value):
    if not isinstance(value, str) or not VIDEO_ID.fullmatch(value):
        raise web.HTTPBadRequest(text="invalid video id")
    return value


async def media_api(path, method="GET", data=None):
    """Call the private music API without exposing API credentials to browser."""
    url="http://127.0.0.1:8765"+path
    headers={"X-API-Key": API_KEY, "Content-Type":"application/json"}
    async with ClientSession(timeout=ClientTimeout(total=45)) as session:
        async with session.request(method,url,headers=headers,json=data) as response:
            result=await response.json(content_type=None)
            if response.status>=400:
                raise ValueError(result.get("error","Audioanbieter nicht verfügbar"))
            return result


async def outputs(request):
    if not SUPERVISOR_TOKEN:
        return web.json_response({"outputs":[]})
    headers={"Authorization":"Bearer "+SUPERVISOR_TOKEN}
    async with ClientSession(timeout=ClientTimeout(total=12)) as session:
        async with session.get("http://supervisor/core/api/states",headers=headers) as response:
            states=await response.json(content_type=None)
    candidates=[]
    for st in states if isinstance(states,list) else []:
        eid=str(st.get("entity_id") or "")
        attrs=st.get("attributes") or {}
        name=str(attrs.get("friendly_name") or eid)
        if not eid.startswith("media_player.") or st.get("state") in ("unknown","unavailable"):
            continue
        if not (int(attrs.get("supported_features") or 0)&PLAY_MEDIA):
            continue
        if re.search(r"youtube_music_live|kreativ_tonie|toniebox|this_device|uberall",eid,re.I):
            continue
        if name.strip().lower() in ("android","this device","überall"):
            continue
        candidates.append({"entity_id":eid,"name":name,
                           "volume":attrs.get("volume_level"),"state":st.get("state")})
    dedup={}
    for p in candidates:
        group=re.sub(r"_\d+$","",p["entity_id"])
        score=(20 if p["entity_id"]==group else 0)+(2 if p["state"]=="playing" else 0)+(1 if p["volume"] is not None else 0)
        if group not in dedup or score>dedup[group][0]:
            dedup[group]=(score,p)
    result=[v[1] for v in dedup.values()]
    result.sort(key=lambda p:p["name"].lower())
    return web.json_response({"outputs":[{"entity_id":p["entity_id"],"name":p["name"]} for p in result]})


async def library(request):
    data=await media_api("/api/library?limit=100")
    return web.json_response({"playlists":data.get("playlists",[])})


async def playlist(request):
    pid=request.query.get("id","")
    if pid!="LM" and not re.fullmatch(r"[A-Za-z0-9_-]{3,200}",pid):
        raise web.HTTPBadRequest(text="invalid playlist")
    data=await media_api("/api/playlist?id="+quote(pid)+"&limit=200")
    return web.json_response(data)


async def search(request):
    q=request.query.get("q","").strip()
    if not (1<=len(q)<=150):
        raise web.HTTPBadRequest(text="invalid search")
    kind=request.query.get("kind","songs")
    if kind not in ("songs","videos","playlists","radios",
                    "featured_playlists","community_playlists"):
        return web.json_response({"error":"Ungültige Kategorie"},status=400)
    data=await media_api("/api/search?q="+quote(q)+"&kind="+kind+"&limit=25")
    return web.json_response({"results":data.get("results",[]),"kind":kind})


async def radio(request):
    vid=safe_video_id(request.query.get("video_id"))
    data=await media_api("/api/recommendations?video_id="+vid+"&limit=30")
    return web.json_response({"tracks":data.get("tracks",[])})


async def settings_get(request):
    status=await media_api("/api/status")
    return web.json_response({"auto_continue_enabled":status.get("auto_continue_enabled",True)})


async def settings_post(request):
    if request.content_type!="application/json":
        return web.json_response({"error":"Ungültige Anfrage"},status=415)
    body=await request.json()
    if type(body.get("enabled")) is not bool:
        return web.json_response({"error":"An oder Aus erforderlich"},status=400)
    status=await media_api("/api/auto_continue","POST",{"enabled":body["enabled"]})
    return web.json_response({"auto_continue_enabled":status["auto_continue_enabled"]})


async def probe(request):
    vid=safe_video_id(request.query.get("video_id"))
    try:
        data=await media_api("/api/probe?video_id="+vid)
        ok=data.get("http_status") in (200,206) and int(data.get("bytes_received") or 0)>0
        if ok:
            # Exercise the real ffmpeg -> MP3 streaming pipeline without
            # handing an audio URL to any media_player or browser <audio>.
            expiry=int(time.time())+90
            signature=hmac.new(API_KEY.encode(),f"{vid}:{expiry}".encode(),
                               hashlib.sha256).hexdigest()
            url=f"http://127.0.0.1:8765/stream/{vid}.mp3?exp={expiry}&sig={signature}"
            try:
                async with ClientSession(timeout=ClientTimeout(total=40)) as client:
                    async with client.get(url) as stream:
                        received=0
                        # FFmpeg sends a 45-byte MP3 header before any frames.
                        # StreamReader.read(n) may return fewer than n bytes.
                        # Wait for actual frames, then close the connection
                        # without sending anything to a physical speaker.
                        while received<2048:
                            chunk=await asyncio.wait_for(
                                stream.content.read(4096),timeout=18)
                            if not chunk:
                                break
                            received+=len(chunk)
                        ok=stream.status==200 and received>=2048
                        if not ok:
                            LOG.warning("phone_preview_pipeline_failed status=%s bytes=%s",
                                        stream.status,received)
            except (OSError, asyncio.TimeoutError) as exc:
                LOG.warning("phone_preview_pipeline_error type=%s",type(exc).__name__)
                ok=False
        if ok:
            TRACKS_VERIFIED[vid]=time.monotonic()
        return web.json_response({"ok":ok,"reason":None if ok else
           "Audiostream konnte nicht vollständig vorbereitet werden."})
    except Exception:
        return web.json_response({"ok":False,
                "reason":"Die Audioquelle konnte nicht abgerufen werden."})


def signed_url(vid):
    expiry=int(time.time())+3600
    signature=hmac.new(API_KEY.encode(),f"{vid}:{expiry}".encode(),hashlib.sha256).hexdigest()
    return f"{BASE_URL}/stream/{vid}.mp3?exp={expiry}&sig={signature}"


async def audio(request):
    vid=safe_video_id(request.match_info.get("vid"))
    # Only a recently probed source may be streamed through the phone UI.
    if vid not in TRACKS_VERIFIED or time.monotonic()-TRACKS_VERIFIED[vid]>300:
        return web.json_response({"error":"Audioquelle zuerst prüfen."},status=409)
    expiry=int(time.time())+90
    signature=hmac.new(API_KEY.encode(),f"{vid}:{expiry}".encode(),hashlib.sha256).hexdigest()
    upstream=f"http://127.0.0.1:8765/stream/{vid}.mp3?exp={expiry}&sig={signature}"
    client=ClientSession(timeout=ClientTimeout(total=None,connect=25,sock_read=35))
    try:
        async with client.get(upstream) as response:
            if response.status!=200:
                return web.json_response({"error":"Audioquelle nicht abrufbar"},status=502)
            streamed=web.StreamResponse(status=200,headers={
              "Content-Type":"audio/mpeg","Cache-Control":"no-store",
              "X-Content-Type-Options":"nosniff"})
            await streamed.prepare(request)
            try:
                async for chunk in response.content.iter_chunked(16384):
                    await streamed.write(chunk)
                await streamed.write_eof()
            except (ConnectionResetError, asyncio.CancelledError):
                LOG.info("phone_preview_disconnected")
            return streamed
    except (OSError, asyncio.TimeoutError):
        LOG.warning("phone_audio_proxy_failed")
        return web.json_response({"error":"Audioübertragung fehlgeschlagen"},status=502)
    finally:
        await client.close()


async def remote(request):
    """Explicit remote playback only; never called by status/metadata/selection."""
    if request.headers.get("X-HausCheck-Intent")!="explicit-remote-playback":
        return web.json_response({"error":"Ausdrückliche Bestätigung fehlt"},status=403)
    if request.content_type!="application/json":
        return web.json_response({"error":"Ungültige Anfrage"},status=415)
    body=await request.json()
    vid=safe_video_id(body.get("video_id"))
    eid=body.get("entity_id")
    if body.get("confirmed_remote") is not True or not isinstance(eid,str):
        return web.json_response({"error":"Freigabe fehlt"},status=403)
    if vid not in TRACKS_VERIFIED or time.monotonic()-TRACKS_VERIFIED[vid]>300:
        return web.json_response({"error":"Audioquelle zuerst prüfen"},status=409)
    all_devices=await outputs(request)
    # Avoid relying on HTTP response internals: verify against current HA state list
    info=json.loads(all_devices.text)
    allowed={p["entity_id"] for p in info.get("outputs",[])}
    if eid not in allowed or eid=="media_player.youtube_music_live_youtube_music_live":
        return web.json_response({"error":"Kein unterstützter Lautsprecher"},status=400)
    payload={"entity_id":eid,"media_content_id":signed_url(vid),
             "media_content_type":"audio/mpeg"}
    headers={"Authorization":"Bearer "+SUPERVISOR_TOKEN,
             "Content-Type":"application/json"}
    async with ClientSession(timeout=ClientTimeout(total=18)) as client:
        async with client.post("http://supervisor/core/api/services/media_player/play_media",
                               headers=headers,json=payload) as response:
            if response.status>=400:
                return web.json_response({"error":"Ausgabegerät hat Wiedergabe abgelehnt"},status=502)
    LOG.info("explicit_remote_preview_requested entity_id=%s",eid)
    return web.json_response({"entity_id":eid,"started":True})


async def page(request):
    return web.Response(text=PAGE,content_type="text/html",
                        headers={"Cache-Control":"no-store"})


async def diagnostics(request):
    def inspect_provider():
        try:
            with socket.create_connection(("127.0.0.1",4416),timeout=1.0):
                return True
        except OSError:
            return False
    import yt_dlp
    available=await asyncio.to_thread(inspect_provider)
    return web.json_response({
        "token_provider_listening":available,
        "provider_binary_present":Path("/opt/bgutil/server/build/main.js").is_file(),
        "yt_dlp_version":yt_dlp.version.__version__,
        "phone_playback_only_by_default":True,
    })


def routes(app):
    app.router.add_get("/player",page)
    app.router.add_get("/api/mobile/diagnostics",diagnostics)
    app.router.add_get("/api/mobile/outputs",outputs)
    app.router.add_get("/api/mobile/library",library)
    app.router.add_get("/api/mobile/playlist",playlist)
    app.router.add_get("/api/mobile/search",search)
    app.router.add_get("/api/mobile/radio",radio)
    app.router.add_get("/api/mobile/settings",settings_get)
    app.router.add_post("/api/mobile/settings",settings_post)
    app.router.add_get("/api/mobile/probe",probe)
    app.router.add_get("/api/mobile/audio/{vid}",audio)
    app.router.add_post("/api/mobile/remote",remote)
