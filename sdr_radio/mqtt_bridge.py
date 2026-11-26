"""Native Home Assistant MQTT discovery and authenticated dashboard command bridge.

The browser never connects to the Supervisor Ingress API directly.
The dashboard calls HA's mqtt.publish service, and receives states through
a discovered sensor. Control API is NOT exposed on any additional port.
"""
import json
import os
import threading
import time
import urllib.request

import paho.mqtt.client as mqtt

TOPIC = "hauscheck/sdr_radio"
STATUS = TOPIC + "/state"
COMMAND = TOPIC + "/command"
AVAILABILITY = TOPIC + "/availability"
DISCOVERY = "homeassistant/sensor/hauscheck_sdr_radio/status/config"


class RadioMqttBridge:
    def __init__(self, status_provider, command_handler):
        self.status_provider = status_provider
        self.command_handler = command_handler
        self.client = None
        self.connected = False
        self.error = ""
        self.last_command_at = 0
        self.last_action = ""
        self.command_lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_requested = False
        self.thread = threading.Thread(target=self._run, name="sdr-mqtt", daemon=True)
        self.thread.start()

    @staticmethod
    def _broker():
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            raise RuntimeError("Supervisor-Token nicht vorhanden")
        req = urllib.request.Request(
            "http://supervisor/services/mqtt",
            headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.load(resp)
        # Supervisor can wrap responses in {data: {...}}.
        obj = data.get("data", data)
        if not isinstance(obj, dict):
            raise ValueError("Unerwartete MQTT-Serviceantwort")
        return obj

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.error = "MQTT-Connect: " + str(reason_code)
            print("SDR MQTT:", self.error, flush=True)
            return
        self.connected = True
        client.subscribe(COMMAND, qos=0)
        config = {
            "name": "SDR Radio",
            "unique_id": "hauscheck_sdr_radio_status",
            "object_id": "sdr_radio",
            "state_topic": STATUS,
            "value_template": "{{ value_json.state }}",
            "json_attributes_topic": STATUS,
            "availability_topic": AVAILABILITY,
            "payload_available": "online",
            "payload_not_available": "offline",
            "icon": "mdi:radio-fm",
            "device": {
                "identifiers": ["hauscheck_sdr_radio_1"],
                "name": "SDR UKW Radio",
                "manufacturer": "HausCheckHAOS",
                "model": "RTL-SDR UKW mit RDS"
            }
        }
        client.publish(DISCOVERY, json.dumps(config), qos=1, retain=True)
        client.publish(AVAILABILITY, "online", qos=1, retain=True)
        print("SDR MQTT: verbunden, Entität via Discovery angemeldet", flush=True)
        self.wake.set()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        print("SDR MQTT: getrennt (" + str(reason_code) + ")", flush=True)

    def _on_message(self, client, userdata, message):
        if message.topic != COMMAND or len(message.payload) > 2048:
            return
        try:
            command = json.loads(message.payload.decode("utf-8"))
            if not isinstance(command, dict):
                return
        except (UnicodeDecodeError, ValueError):
            return

        def handle():
            with self.command_lock:
                try:
                    action = str(command.get("action", ""))
                    if action not in ("tune", "seek", "step", "play", "stop_output",
                                      "stop_tuner", "select_output",
                                      "add_favorite", "remove_favorite"):
                        raise ValueError("Unbekannte Radioaktion")
                    self.command_handler(action, command)
                    self.error = ""
                    self.last_action = action
                    self.last_command_at = time.time()
                except Exception as exc:
                    self.error = str(exc)[:200]
                    self.last_action = str(command.get("action", ""))
                    self.last_command_at = time.time()
                    print("SDR MQTT-Befehl:", self.error, flush=True)
                finally:
                    self.wake.set()
        threading.Thread(target=handle, daemon=True).start()

    def _publish_status(self):
        if not self.connected or not self.client:
            return
        state = self.status_provider()
        if not isinstance(state, dict):
            return
        # Avoid publishing high-frequency counters or whole signal scan logs.
        # MQTT attributes are small and change only when user-facing info changes.
        value = {
            "state": "on" if state.get("running") else "off",
            "running": bool(state.get("running")),
            "frequency": state.get("frequency"),
            "station": state.get("station") or {},
            "song": state.get("song") or {},
            "rds": {
                "pi": (state.get("rds") or {}).get("pi"),
                "ps": (state.get("rds") or {}).get("ps"),
                "radiotext": (state.get("rds") or {}).get("radiotext")
            },
            "station_name_source": state.get("station_name_source"),
            "presets": (state.get("presets") or [])[:50],
            "selected_output": state.get("selected_output"),
            "output_state": state.get("output_state"),
            "output_playing": bool(state.get("output_playing")),
            "output_volume": state.get("output_volume"),
            "output_stream_connected": bool(state.get("output_stream_connected")),
            "output_recovering": bool(state.get("output_recovering")),
            "output_status_reason": state.get("output_status_reason") or "",
            "output_retry_count": state.get("output_retry_count", 0),
            "stream_url": state.get("stream_url"),
            "last_command_error": self.error,
            "last_action": self.last_action,
            "last_command_at": self.last_command_at
        }
        self.client.publish(STATUS, json.dumps(value, ensure_ascii=False), qos=0, retain=True)

    def _run(self):
        while not self.stop_requested:
            try:
                service = self._broker()
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                     client_id="hauscheck_sdr_radio")
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                client.will_set(AVAILABILITY, "offline", qos=1, retain=True)
                if service.get("username"):
                    client.username_pw_set(str(service["username"]),
                                           str(service.get("password") or ""))
                if service.get("ssl"):
                    client.tls_set()
                self.client = client
                client.connect(str(service.get("host") or "core-mosquitto"),
                               int(service.get("port", 1883)), keepalive=45)
                client.loop_start()
                while not self.stop_requested:
                    self.wake.wait(timeout=3)
                    self.wake.clear()
                    if not client.is_connected():
                        # Paho reconnects automatically.
                        continue
                    try:
                        self._publish_status()
                    except Exception as exc:
                        print("SDR MQTT Status:", str(exc)[:200], flush=True)
                client.publish(AVAILABILITY, "offline", qos=1, retain=True)
                client.disconnect()
                client.loop_stop()
            except Exception as exc:
                print("SDR MQTT Broker noch nicht verfügbar:", str(exc)[:200], flush=True)
                self.connected = False
                time.sleep(20)
