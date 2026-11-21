"""Stateful RDS PS / PI / RT / RT+ metadata from redsea (one RTL-SDR dongle).

RDS RT+ has priority. Plain RT is displayed as radio text, and parsed as
a track ONLY on a clear artist - title pattern. External providers are
used for cover lookup, never to replace an RDS-recognized title.
"""
import re
import threading
import time
from radio_metadata import artwork_for, clean, key

def safe_ps(value):
    s = clean(value, 80).strip()
    if not s or len(s)<2 or not any(c.isalnum() for c in s):
        return ""
    return s


def rt_song(text):
    raw=clean(text,260)
    for sep in (" - "," – "," — "," | "):
        if sep in raw:
            artist,title=raw.split(sep,1)
            artist,title=artist.strip(),title.strip()
            if 2<=len(artist)<=95 and 2<=len(title)<=135 and all(x not in raw.lower() for x in
                ("http","www.","radio station","werbung","nachrichten","verkehr","wetter")):
                return {"artist":artist,"title":title,"source":"RDS RadioText"}
    return None


def yt_cover(artist,title):
    """Use Dudu7's YT Music-first / strong-match approach, if available."""
    try:
        from ytmusicapi import YTMusic
        songs=YTMusic().search(f"{artist} - {title}",filter="songs",limit=8)
        a,t=key(artist),key(title)
        for song in songs:
            st=key(song.get("title"))
            artists=" ".join(x.get("name","") for x in song.get("artists",[]))
            sa=key(artists)
            if not st or not sa or not a or not t:
                continue
            good_title=(st==t or (len(t)>6 and (st.startswith(t) or t.startswith(st))))
            good_artist=(sa==a or a in sa or sa in a)
            if not good_title or not good_artist:
                continue
            thumbs=song.get("thumbnails") or []
            if thumbs:
                uri=thumbs[-1].get("url","")
                if uri.startswith("https://"):
                    # YouTube Music artwork often supports 544px or larger.
                    return uri.replace("w120-h120","w544-h544")
    except Exception as exc:
        print("YTMusic artwork lookup:",str(exc)[:140],flush=True)
    return ""


class RDSState:
    def __init__(self):
        self.lock=threading.RLock()
        self.generation=0
        self.reset(None)
        self.cover_cache={}
        self.cover_pending=set()
        self.cover_lock=threading.Lock()

    def reset(self,freq):
        with self.lock:
            self.generation=getattr(self,"generation",0)+1
            self.frequency=freq
            self.pi=""
            self.ps=""
            self.rt=""
            self.song=None
            self.updated=0
            self.groups=0
            self.rtplus=False
            self.cover_source=""

    def feed(self,event,freq=None):
        if not isinstance(event,dict):return
        with self.lock:
            if freq is not None and self.frequency!=freq:return
            pi=event.get("pi")
            if isinstance(pi,str) and re.fullmatch(r"0x[0-9a-fA-F]{4}",pi):
                self.pi=pi[2:].upper()
            ps=safe_ps(event.get("ps"))
            if ps:self.ps=ps
            rt=event.get("radiotext") or event.get("radiotext_utf8") or event.get("enhanced_radiotext")
            if isinstance(rt,str):
                rt=clean(rt.strip("\x00 "),260)
                if rt and rt!=self.rt:
                    self.rt=rt
                    self.song=rt_song(rt)
                    self.rtplus=False
            rtplus=event.get("radiotext_plus") or {}
            if isinstance(rtplus,dict) and rtplus.get("item_running") is not False:
                tags=rtplus.get("tags") or []
                parts={}
                for tag in tags:
                    if not isinstance(tag,dict):continue
                    typ=str(tag.get("content-type","")).lower()
                    val=clean(tag.get("data"),150)
                    if typ=="item.artist" and val:parts["artist"]=val
                    if typ=="item.title" and val:parts["title"]=val
                if len(parts)==2:
                    self.song={**parts,"source":"RDS RT+"}
                    self.rtplus=True
            self.groups+=1
            self.updated=time.time()
            song=dict(self.song) if self.song else None
            generation=self.generation
        if song and song.get("artist") and song.get("title"):
            self._cover(song,generation)

    def _cover(self,song,generation):
        k=key(song["artist"])+"/"+key(song["title"])
        with self.cover_lock:
            if k in self.cover_cache:
                with self.lock:
                    if self.generation==generation and self.song and (
                        key(self.song.get("artist"))+"/"+key(self.song.get("title")))==k:
                        self.song["cover_url"]=self.cover_cache[k][0]
                        self.cover_source=self.cover_cache[k][1]
                return
            if k in self.cover_pending:return
            self.cover_pending.add(k)
        def lookup():
            cover=yt_cover(song["artist"],song["title"])
            source="YouTube Music" if cover else ""
            if not cover:
                cover=artwork_for(song["artist"],song["title"])
                source="iTunes" if cover else ""
            with self.cover_lock:
                self.cover_cache[k]=(cover,source)
                self.cover_pending.discard(k)
                if len(self.cover_cache)>100:
                    self.cover_cache.pop(next(iter(self.cover_cache)))
            with self.lock:
                if self.generation==generation and self.song and (
                    key(self.song.get("artist"))+"/"+key(self.song.get("title")))==k:
                    self.song["cover_url"]=cover
                    self.cover_source=source
        threading.Thread(target=lookup,daemon=True).start()

    def status(self):
        with self.lock:
            return {"rds":{"pi":self.pi,"ps":self.ps,"radiotext":self.rt,
                           "groups":self.groups,"rtplus":self.rtplus,
                           "updated_at":self.updated,
                           "cover_source":self.cover_source},
                    "rds_song":dict(self.song) if self.song else None}
