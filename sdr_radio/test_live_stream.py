"""Offline regression tests; no SDR or HA required."""
import ast
import pathlib
import queue
import threading
import time
import unittest
import secrets
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import socket
from urllib.parse import urlsplit, parse_qs

source = pathlib.Path(__file__).with_name("main.py").read_text()
tree = ast.parse(source)
classes = [x for x in tree.body if isinstance(x, ast.ClassDef)
           and x.name in ("RadioOutput", "Handler")]
code = compile(ast.Module(body=classes, type_ignores=[]), "main.py", "exec")

class FakeRadio:
    def __init__(self):
        self.lock = threading.RLock()
        self.stream_clients = {}
        self.stream_events = deque()
        self.stream_history = deque()
        self.subscribers = set()
        self.session_gen = 1
        self.encoder = object()
    def _running_locked(self):
        return self.encoder is not None
    def status(self):
        return {"running": self._running_locked(), "frequency": 99.7}

class Tests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.radio = FakeRadio()
        self.player = {"state":"playing","attributes":{}}
        self.local = {"state":"on","attributes":{"source":"WIFI_GOOGLE"}}
        self.yt = {"attributes":{}}
        self.calls = []
        def request(path, payload=None):
            if path == "states/media_player.cast": return self.player
            if path == "states/local": return self.local
            if path == "states/yt": return self.yt
            self.calls.append((path, payload))
            if path.endswith("/play_media"):
                self.player["attributes"]["media_content_id"] = payload["media_content_id"]
            return {}
        self.ns = dict(globals(), DATA=pathlib.Path("/tmp"), radio=self.radio,
            STREAM_BASE="http://localhost:8099", MP3_BITRATE=160,
            STREAM_HTTP_PROFILE="chunked", SOUNDBAR_CAST="media_player.cast", SOUNDBAR_LOCAL="local",
            YT_STATUS="yt", load_json=lambda *a:{}, save_json=lambda *a:None,
            ha_request=request, metadata=Mock(),
            time=SimpleNamespace(monotonic=lambda:self.now, strftime=time.strftime, localtime=time.localtime))
        exec(code, self.ns)
        self.out = self.ns["RadioOutput"]()
        self.out.play(None)
    def disconnect(self, reason="BrokenPipeError"):
        self.radio.stream_events.append({"session":self.out.session,
                                         "at":self.now, "reason":reason})
        self.radio.stream_clients.clear()
    def connected(self):
        self.radio.stream_clients[object()]={"session":self.out.session,"last_write":self.now}
        self.assertTrue(self.out.output_state()["output_playing"])
    def test_status_and_retry(self):
        self.assertFalse(self.out.output_state()["output_playing"])
        self.connected()
        self.disconnect()
        self.now += 5
        self.assertFalse(self.out.output_state()["output_playing"])
        self.assertEqual(len(self.calls),1)
        self.now += 12
        old=self.out.session
        state=self.out.output_state()
        self.assertTrue(state["output_recovering"])
        self.assertNotEqual(old,self.out.session)
        self.assertEqual(len(self.calls),2)
        self.connected()
        self.assertFalse(self.out.recovering)
    def test_stop_disarms(self):
        self.connected()
        self.disconnect()
        self.out.stop()
        self.now += 30
        self.out.output_state()
        self.assertEqual([x[0] for x in self.calls],["services/media_player/play_media","services/media_player/media_stop"])
    def test_external_stop(self):
        self.connected()
        self.disconnect()
        self.player["state"]="idle"
        self.now += 30
        self.out.output_state()
        self.assertIsNone(self.out.active)
        self.assertEqual(len(self.calls),1)
    def test_other_source(self):
        self.connected()
        self.disconnect()
        self.local["attributes"]["source"]="eARC"
        self.now += 30
        self.out.output_state()
        self.assertIsNone(self.out.active)
        self.assertEqual(len(self.calls),1)
    def test_other_media(self):
        self.connected()
        self.disconnect()
        self.player["attributes"]["media_content_id"]="http://other"
        self.now += 30
        self.out.output_state()
        self.assertEqual(len(self.calls),1)
    def test_yt_guard(self):
        self.connected()
        self.disconnect()
        self.yt["attributes"].update(selected_output="media_player.cast",player_state="starting")
        self.now += 30
        self.out.output_state()
        self.assertEqual(len(self.calls),1)
    def test_limit(self):
        self.connected()
        for i in range(3):
            self.disconnect()
            self.now += 20
            self.out.output_state()
            self.connected()
        self.disconnect()
        self.now += 20
        self.out.output_state()
        self.assertEqual(len(self.calls),4)
        self.assertIsNone(self.out.active)
    def test_chunked_and_close_headers(self):
        self.ns["time"] = time
        for profile in ("chunked","close"):
            self.ns["STREAM_HTTP_PROFILE"]=profile
            handler=self.ns["Handler"]
            server=ThreadingHTTPServer(("127.0.0.1",0),handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            try:
                conn.request("GET","/stream.mp3?session=test")
                res=conn.getresponse()
                self.assertEqual(res.status,200)
                self.assertEqual(res.getheader("icy-br"),"160")
                self.assertIsNone(res.getheader("Content-Length"))
                self.assertEqual(res.getheader("Transfer-Encoding"),"chunked" if profile=="chunked" else None)
                with self.radio.lock:
                    next(iter(self.radio.subscribers)).put(b"test")
                self.assertEqual(res.read(4),b"test")
                with self.radio.lock:
                    self.radio.session_gen+=1
                self.assertEqual(res.read(),b"")
            finally:
                conn.close()
                server.shutdown()
                server.server_close()

if __name__ == "__main__":
    unittest.main()
