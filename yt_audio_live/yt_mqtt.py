"""MQTT bridge for the HA dashboard – no API key or Google cookies in the card.

Read actions (search/library) never play audio. Playback requires an explicit,
validated physical output and an explicit confirmed action.
"""
import json
import logging
import os
import random
import re
import threading
import time
import urllib.request
from collections import deque

import paho.mqtt.client as mqtt

LOG = logging.getLogger("yt_audio_live.mqtt")
ROOT = "hauscheck/ytmusic_live"
COMMAND = ROOT + "/command"
STATUS = ROOT + "/state"
AVAILABLE = ROOT + "/availability"
DISCOVERY = "homeassistant/sensor/hauscheck_ytmusic_live/status/config"
FEATURE_PLAY_MEDIA = 131072
EXCLUDE = re.compile(r"youtube_music_live|kreativ_tonie|toniebox|this_device|uberall", re.I)

class MusicMqttBridge:
    def __init__(self, catalog_provider, player, resolve_source, warm_source=None):
        self.catalog_provider = catalog_provider
        self.player = player
        self.resolve_source = resolve_source
        self.warm_source = warm_source or (lambda vid: None)
        self._next_warm_at = 0.0
        self._next_warm_vid = None
        self._playlist_cache = {}
        self.connected = False
        self.client = None
        self.lock = threading.RLock()
        self.command_lock = threading.Lock()
        self.wake = threading.Event()
        self.info = {
            "search_query": "", "search_kind": "songs", "search_results": [],
            "playlists": [], "list_playlist_id": "", "list_title": "", "list_tracks": [],
            "last_error": "", "last_action": "", "last_command_at": 0
        }
        threading.Thread(target=self._run, daemon=True, name="ytmusic-mqtt").start()

    @staticmethod
    def _broker():
        token=os.environ.get("SUPERVISOR_TOKEN","")
        req=urllib.request.Request("http://supervisor/services/mqtt",
                                   headers={"Authorization":"Bearer "+token})
        with urllib.request.urlopen(req,timeout=8) as response:
            result=json.load(response)
        return result.get("data",result)

    def _current(self):
        with self.lock:
            return dict(self.info)

    def _set(self, **values):
        with self.lock:
            self.info.update(values)
            self.info["last_command_at"]=round(time.time(),3)
        self.wake.set()

    def _validate_output(self, entity_id):
        if not isinstance(entity_id,str) or not re.fullmatch(r"media_player\.[a-z0-9_]+",entity_id):
            raise ValueError("Bitte ein gültiges Ausgabegerät auswählen")
        if EXCLUDE.search(entity_id):
            raise ValueError("Dieses Gerät kann keine Musikstreams abspielen")
        info=self.player._request("/states/"+entity_id)
        name=str((info.get("attributes") or {}).get("friendly_name") or entity_id)
        if info.get("state") in ("unavailable","unknown") or (
          int((info.get("attributes") or {}).get("supported_features") or 0) & FEATURE_PLAY_MEDIA
        )==0:
            raise ValueError("Ausgabegerät unterstützt keine MP3-Wiedergabe")
        return name

    def _prepare_output(self, cmd):
        # An empty output is rejected; never implicitly fall back to soundbar.
        eid=cmd.get("entity_id")
        self._validate_output(eid)
        if cmd.get("confirmed") is not True:
            raise ValueError("Wiedergabe muss ausdrücklich bestätigt werden")
        self.player.set_output(eid)

    def _find_track(self, vid):
        if not isinstance(vid,str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):
            raise ValueError("Ungültiger Titel")
        for t in (self.info.get("search_results",[]) +
                  self.info.get("list_tracks",[])):
            if t.get("video_id")==vid:
                return t
        return {"video_id":vid,"title":vid,"artist":""}

    def _playlist(self, catalog, pid, refresh=False):
        # Reuse the list just opened by the user, instead of downloading it twice.
        now = time.monotonic()
        entry = self._playlist_cache.get(pid)
        if not refresh and entry and entry[0] is catalog and now - entry[1] < 90:
            LOG.info("playlist_cache_hit")
            return entry[2]
        data = catalog.playlist(pid, limit=200)
        self._playlist_cache[pid] = (catalog, time.monotonic(), data)
        while len(self._playlist_cache) > 5:
            self._playlist_cache.pop(next(iter(self._playlist_cache)))
        return data

    def _warm(self, track):
        self._warm_many([track])

    def _warm_many(self, tracks):
        ids = [t["video_id"] for t in tracks if isinstance(t, dict)
               and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(t.get("video_id") or ""))]
        if ids:
            self.warm_source(ids[:4])

    def _handle(self, cmd):
        action=cmd.get("action")
        catalog=self.catalog_provider()
        if action=="warm_current":
            status = self.player.status()
            if status.get("cast_state") == "stopped" and status.get("player_entity") == cmd.get("entity_id"):
                self._warm_many([status.get("current")] + (status.get("queue") or [])[:3])
            return
        if action=="library":
            lists=catalog.library_playlists(limit=100)
            self._set(playlists=lists[:100],last_action=action,last_error="")
            return
        if action=="search":
            query=str(cmd.get("query") or "").strip()
            kind=str(cmd.get("kind") or "songs")
            if kind not in ("songs","videos","playlists","featured_playlists",
                            "community_playlists","radios"):
                raise ValueError("Ungültige Suchkategorie")
            items=catalog.search(query,kind=kind,limit=22)
            self._set(search_query=query,search_kind=kind,search_results=items[:22],
                      last_action=action,last_error="")
            if items and kind in ("songs","videos","radios"):
                self._warm_many(items[:4])
            return
        if action=="load_playlist":
            pid=str(cmd.get("playlist_id") or "")
            data=self._playlist(catalog,pid,refresh=True)
            self._set(list_playlist_id=pid,list_title=data["title"],list_tracks=data["tracks"][:55],
                      last_action=action,last_error="")
            if data["tracks"]:
                self._warm_many(data["tracks"][:4])
            return
        if action=="radio_preview":
            vid=str(cmd.get("video_id") or "")
            tracks=catalog.radio(vid,limit=35)
            self._set(list_title="Radio zu "+str(cmd.get("title") or vid)[:90],
                      list_tracks=tracks[:35],last_action=action,last_error="")
            return
        if action=="enqueue":
            track=self._find_track(cmd.get("video_id"))
            self.player.enqueue([track])
            self._set(last_action=action,last_error="")
            return
        if action=="history_play":
            self.player.play_history(cmd.get("index"),cmd.get("video_id"))
            self._set(last_action=action,last_error="")
            return
        if action=="queue_play":
            self.player.play_queued(cmd.get("index"),cmd.get("video_id"))
            self._set(last_action=action,last_error="")
            return
        if action=="select_output":
            eid=cmd.get("entity_id")
            self._validate_output(eid)
            self.player.set_output(eid)
            self._set(last_action=action,last_error="")
            return
        if action=="auto_continue":
            if type(cmd.get("enabled")) is not bool:
                raise ValueError("Autoplay benötigt An oder Aus")
            self.player.set_auto_continue(cmd["enabled"])
        elif action=="shuffle":
            self.player.set_shuffle(cmd.get("enabled") is True)
        elif action=="repeat":
            self.player.set_repeat(cmd.get("mode"))
        elif action in ("start_track","start_radio"):
            self._prepare_output(cmd)
            track=self._find_track(cmd.get("video_id"))
            self.resolve_source(track["video_id"])
            if action=="start_radio":
                recommended=catalog.radio(track["video_id"],limit=35)
                self.player.start(track,rest=recommended,radio=True)
            else:
                self.player.start(track,radio=False)
        elif action=="start_playlist_track":
            # Starting a song inside a playlist must continue with that playlist,
            # rather than turning it into a one-song playback session.
            # The index is advisory and verified against the video ID so stale
            # dashboard results cannot start a different track.
            self._prepare_output(cmd)
            pid=str(cmd.get("playlist_id") or "")
            vid=cmd.get("video_id")
            if not isinstance(vid,str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):
                raise ValueError("Ungültiger Titel")
            tracks=self._playlist(catalog,pid)["tracks"]
            index=cmd.get("index")
            if type(index) is not int or not 0<=index<len(tracks) or tracks[index]["video_id"]!=vid:
                index=next((i for i,track in enumerate(tracks)
                            if track["video_id"]==vid),-1)
            if index<0:
                raise ValueError("Dieser Titel ist nicht mehr in der Playlist")
            # The chosen track stays first even with shuffle active. Playback.start
            # shuffles only the remaining tracks when Shuffle is enabled.
            current=tracks[index]
            rest=tracks[index+1:]
            self.resolve_source(current["video_id"])
            self.player.start(current,rest=rest,radio=False)
        elif action=="start_playlist":
            self._prepare_output(cmd)
            data=self._playlist(catalog,str(cmd.get("playlist_id") or ""))
            items=data["tracks"]
            if not items:
                raise ValueError("Diese Playlist enthält keine verfügbaren Titel")
            # When shuffle is active choose a random first track as well.
            if self.player.shuffle_enabled and len(items)>1:
                random.SystemRandom().shuffle(items)
            self.resolve_source(items[0]["video_id"])
            self.player.start(items[0],rest=items[1:],radio=False)
        elif action=="radio_toggle":
            self.player.set_radio(cmd.get("enabled") is True)
        elif action=="stop":
            self.player.stop()
        elif action=="seek":
            self.player.seek(cmd.get("position"))
        elif action=="pause":
            self.player.pause()
        elif action=="resume":
            self.player.resume()
        elif action=="next":
            self.player.next()
        elif action=="previous":
            self.player.previous()
        else:
            raise ValueError("Unbekannter Musikbefehl")
        self._set(last_action=action,last_error="")

    def _on_connect(self,client,userdata,flags,reason_code,properties):
        if reason_code.is_failure:
            LOG.warning("mqtt_connect_refused")
            return
        self.connected=True
        client.subscribe(COMMAND,qos=0)
        client.publish(DISCOVERY,json.dumps({
          "name":"YouTube Music Live",
          "unique_id":"hauscheck_ytmusic_live_hub",
          "object_id":"hauscheck_ytmusic_live",
          "state_topic":STATUS,
          "value_template":"{{ value_json.state }}",
          "json_attributes_topic":STATUS,
          "availability_topic":AVAILABLE,
          "icon":"mdi:music-circle",
          "device":{"identifiers":["hauscheck_ytmusic_live_1"],
                    "name":"YouTube Music Live","manufacturer":"HausCheckHAOS"}
        }),retain=True,qos=1)
        client.publish(AVAILABLE,"online",qos=1,retain=True)
        LOG.info("ytmusic_mqtt_discovery_connected")
        self.wake.set()
        # Read-only library preload cannot trigger audio.
        threading.Thread(target=lambda:self._load_library(),daemon=True).start()

    def _load_library(self):
        try:
            self._handle({"action":"library"})
        except Exception as exc:
            LOG.warning("library_cache_failed type=%s",type(exc).__name__)

    def _on_disconnect(self,client,userdata,disconnect_flags,reason_code,properties):
        self.connected=False

    def _on_message(self,client,userdata,message):
        if message.topic!=COMMAND or len(message.payload)>4096:
            return
        try:
            cmd=json.loads(message.payload.decode("utf-8"))
            if not isinstance(cmd,dict):
                return
        except (ValueError,UnicodeDecodeError):
            return

        def work():
            with self.command_lock:
                try:
                    self._handle(cmd)
                except Exception as exc:
                    # Never log user search terms or Google session data.
                    self._set(last_error=str(exc)[:190],
                              last_action=str(cmd.get("action",""))[:32])
                    LOG.warning("music_command_failed action=%s error_type=%s",
                                str(cmd.get("action",""))[:32],type(exc).__name__)
                finally:
                    self.wake.set()
        threading.Thread(target=work,name="ytmusic-command",daemon=True).start()

    def _publish(self):
        if not self.connected or not self.client:
            return
        current=self.player.status()
        info=self._current()
        current_track=current.get("current")
        # Warm the next four in queue order, without downloading complete songs.
        queue = current.get("queue") or []
        if current_track and current.get("cast_state") in ("playing", "starting", "buffering") and queue:
            candidates = queue[:4]
            vids = tuple(t.get("video_id") for t in candidates)
            now = time.monotonic()
            if vids != self._next_warm_vid or now - self._next_warm_at >= 30:
                self._next_warm_vid, self._next_warm_at = vids, now
                self._warm_many(candidates)
        else:
            self._next_warm_vid = None
        state="playing" if current_track and current.get("cast_state")=="playing" else "idle"
        data={
          "state":state,
          "current":current_track,
          "queue":(current.get("queue") or []),
          "history":(current.get("history") or []),
          "history_length":current.get("history_length",0),
          "media_position":current.get("media_position",0),
          "media_position_updated_at":current.get("media_position_updated_at"),
          "queue_length":current.get("queue_length",0),
          "player_state":current.get("cast_state"),
          "selected_output":current.get("player_entity"),
          "radio_enabled":current.get("radio_enabled",False),
          "auto_continue_enabled":current.get("auto_continue_enabled",True),
          "shuffle_enabled":current.get("shuffle_enabled",False),
          "repeat_mode":current.get("repeat_mode","off"),
          "search_query":info["search_query"],"search_kind":info["search_kind"],
          "search_results":info["search_results"][:20],
          "playlists":info["playlists"][:65],
          "list_playlist_id":info["list_playlist_id"],
          "list_title":info["list_title"],"list_tracks":info["list_tracks"][:40],
          "last_error":info["last_error"],
          "last_action":info["last_action"],
          "last_command_at":info["last_command_at"]
        }
        self.client.publish(STATUS,json.dumps(data,ensure_ascii=False),retain=True,qos=0)

    def _run(self):
        while True:
            try:
                broker=self._broker()
                client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="hauscheck_ytmusic_live")
                client.on_connect=self._on_connect
                client.on_disconnect=self._on_disconnect
                client.on_message=self._on_message
                client.will_set(AVAILABLE,"offline",retain=True,qos=1)
                if broker.get("username"):
                    client.username_pw_set(str(broker["username"]),
                                           str(broker.get("password") or ""))
                if broker.get("ssl"):
                    client.tls_set()
                self.client=client
                client.connect(str(broker.get("host") or "core-mosquitto"),
                               int(broker.get("port",1883)),keepalive=45)
                client.loop_start()
                wait_started=time.monotonic()
                was_connected=False
                while True:
                    self.wake.wait(timeout=3)
                    self.wake.clear()
                    if client.is_connected():
                        was_connected=True
                        self._publish()
                    elif was_connected or time.monotonic()-wait_started>30:
                        break
                self.connected=False
                client.disconnect()
                client.loop_stop()
            except Exception as exc:
                self.connected=False
                LOG.warning("mqtt_bridge_retry reason=%s",type(exc).__name__)
            time.sleep(12)
