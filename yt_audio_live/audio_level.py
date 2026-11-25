"""Receiver-free audio level diagnostics and bounded output attenuation."""
import json
import math
import os
import re
import subprocess
import threading
from pathlib import Path

class AudioLevel:
    def __init__(self, path="/data/ytmusic-audio-level.json"):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.gain = 0.0
        try:
            self.gain = self.validate(json.loads(self.path.read_text())["gain_db"])
        except (OSError, ValueError, TypeError, KeyError):
            pass

    @staticmethod
    def validate(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("gain_db must be a number between -18 and 0")
        value = float(value)
        if not math.isfinite(value) or not -18 <= value <= 0:
            raise ValueError("gain_db must be between -18 and 0")
        return round(value, 1)

    def set(self, value):
        value = self.validate(value)
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"gain_db": value}, f)
            os.replace(tmp, self.path)
            self.gain = value
        return {"gain_db": value}

    def filter_args(self):
        return ["-af", f"volume={self.gain:.1f}dB"] if self.gain else []

def input_args(url, headers, start=0):
    args = ["ffmpeg", "-hide_banner", "-nostdin"]
    for header, switch in (("User-Agent", "-user_agent"), ("Referer", "-referer")):
        value = headers.get(header)
        if isinstance(value, str) and value and "\r" not in value and "\n" not in value:
            args.extend((switch, value))
    args.extend(["-rw_timeout", "15000000"])
    if start:
        args.extend(["-ss", str(start)])
    return args + ["-i", url, "-vn", "-map", "0:a:0"]

def parse_levels(stderr):
    fields = {}
    patterns = {
        "rms_dbfs": r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB",
        "peak_dbfs": r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB",
        "integrated_lufs": r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS",
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, stderr)
        if not matches:
            raise RuntimeError("Audio level measurement incomplete")
        fields[key] = float(matches[-1])
    return fields

def measure(url, headers, start, duration):
    command = input_args(url, headers, start)
    # No audio output or retained file; just decode a bounded excerpt.
    command.extend(["-t", str(duration), "-nostats", "-loglevel", "info",
                    "-af", "ebur128=framelog=verbose,volumedetect",
                    "-f", "null", "-"])
    result = subprocess.run(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            timeout=45, check=False)
    if result.returncode:
        raise RuntimeError("Audio level measurement failed")
    return parse_levels(result.stderr.decode("utf-8", "replace"))
