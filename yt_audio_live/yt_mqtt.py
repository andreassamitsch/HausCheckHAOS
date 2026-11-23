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
    def __init__(self, catalog_provider, player, resolve_source):
        self.catalog_provider = catalog_provider
        self.player = player
        self.resolve_source = resolve_source
        self.connected = False
        self.client = None
        self.lock = threading.RLock()
        self.command_lock = threading.Lock()
        self.wake = threading.Event()
        self.info = {
            "search_query": "", "search_kind": "songs", "search_results": [],
            "playlists": [], "list_title": "", "list_tracks": [],
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

    def _handle(self, cmd):
        action=cmd.get("action")
        catalog=self.catalog_provider()
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
            return
        if action=="load_playlist":
            pid=str(cmd.get("playlist_id") or "")
            data=catalog.playlist(pid,limit=100)
            self._set(list_title=data["title"],list_tracks=data["tracks"][:55],
                      last_action=action,last_error="")
            return
        if action=="select_output":
            eid=cmd.get("entity_id")
            self._validate_output(eid)
            self.player.set_output(eid)
            self._set(last_action=action,last_error="")
            return
        if action=="shuffle":
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
        elif action=="start_playlist":
            self._prepare_output(cmd)
            data=catalog.playlist(str(cmd.get("playlist_id") or ""),limit=200)
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
        state="playing" if current_track and current.get("cast_state")=="playing" else "idle"
        data={
          "state":state,
          "current":current_track,
          "queue":(current.get("queue") or [])[:25],
          "queue_length":current.get("queue_length",0),
          "player_state":current.get("cast_state"),
          "selected_output":current.get("player_entity"),
          "radio_enabled":current.get("radio_enabled",False),
          "shuffle_enabled":current.get("shuffle_enabled",False),
          "repeat_mode":current.get("repeat_mode","off"),
          "search_query":info["search_query"],"search_kind":info["search_kind"],
          "search_results":info["search_results"][:20],
          "playlists":info["playlists"][:65],
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
                while client.is_connected():
                    self.wake.wait(timeout=3)
                    self.wake.clear()
                    self._publish()
                self.connected=False
                client.loop_stop()
            except Exception as exc:
                self.connected=False
                LOG.warning("mqtt_bridge_retry reason=%s",type(exc).__name__)
            time.sleep(12)
