"""Start the private Firefox login display only when explicitly requested.

The music API and private YouTube session never depend on a running browser.
All three graphical processes are owned by the Ingress auth UI, shut down
after session capture or 8 minutes without user input, and stopped on exit.
"""
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

LOG = logging.getLogger("yt_audio_live.browser")
PROFILE = Path("/data/ytmusic_auth_browser")
IDLE_SECONDS = 8 * 60


class LoginBrowser:
    def __init__(self):
        self.lock = threading.RLock()
        self.processes = {}
        self.last_activity = 0.0

    def _live(self):
        return bool(self.processes) and all(
            proc.poll() is None for proc in self.processes.values()
        )

    def status(self):
        with self.lock:
            return {
                "browser_running": self._live(),
                "idle_timeout_seconds": IDLE_SECONDS,
            }

    def touch(self):
        with self.lock:
            if self._live():
                self.last_activity = time.monotonic()

    @staticmethod
    def _vnc_ready():
        try:
            with socket.create_connection(("127.0.0.1", 5900), timeout=0.5):
                return True
        except OSError:
            return False

    @staticmethod
    def _launch(args, environment):
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=environment,
            start_new_session=True,
        )

    def start(self):
        with self.lock:
            if self._live() and self._vnc_ready():
                self.last_activity = time.monotonic()
                return self.status()
            self._stop_locked()
            PROFILE.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(PROFILE, 0o700)
            prefs = PROFILE / "user.js"
            prefs.write_text(
                'user_pref("signon.rememberSignons", false);\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("browser.startup.homepage", "https://music.youtube.com");\n'
                'user_pref("browser.newtabpage.enabled", false);\n'
                'user_pref("browser.aboutConfig.showWarning", false);\n'
                'user_pref("layout.css.devPixelsPerPx", "1.30");\n',
                encoding="utf-8",
            )
            os.chmod(prefs, 0o600)
            env = os.environ.copy()
            env.update({"DISPLAY": ":99", "HOME": "/data"})
            try:
                self.processes["display"] = self._launch([
                    "Xvfb", ":99", "-screen", "0", "680x900x24",
                    "-nolisten", "tcp", "-ac",
                ], env)
                time.sleep(0.4)
                if self.processes["display"].poll() is not None:
                    raise RuntimeError("Virtuelle Anzeige konnte nicht starten")
                self.processes["vnc"] = self._launch([
                    "x11vnc", "-display", ":99", "-rfbport", "5900",
                    "-localhost", "-forever", "-shared", "-nopw", "-quiet",
                ], env)
                self.processes["firefox"] = self._launch([
                    "firefox-esr", "--no-remote", "--kiosk", "--profile",
                    str(PROFILE), "https://music.youtube.com",
                ], env)
                for _ in range(40):
                    if not self._live():
                        raise RuntimeError("Anmeldebrowser wurde unerwartet beendet")
                    if self._vnc_ready():
                        self.last_activity = time.monotonic()
                        LOG.info("login_browser_started_on_demand")
                        return self.status()
                    time.sleep(0.2)
                raise RuntimeError("Anmeldebrowser ist nicht erreichbar")
            except Exception:
                self._stop_locked()
                raise

    def _stop_locked(self):
        processes = self.processes
        self.processes = {}
        for key in ("firefox", "vnc", "display"):
            proc = processes.get(key)
            if proc is None or proc.poll() is not None:
                continue
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for proc in processes.values():
            try:
                proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=0.8)
                except subprocess.TimeoutExpired:
                    LOG.warning("browser_process_did_not_exit")
        self.last_activity = 0.0

    def stop(self, reason="manual"):
        with self.lock:
            was_running = bool(self.processes)
            self._stop_locked()
        if was_running:
            LOG.info("login_browser_stopped reason=%s", reason)
        return self.status()

    def idle_check(self):
        with self.lock:
            if (self._live() and self.last_activity
                    and time.monotonic() - self.last_activity >= IDLE_SECONDS):
                self._stop_locked()
                LOG.info("login_browser_stopped reason=idle_timeout")
                return True
        return False


BROWSER = LoginBrowser()
