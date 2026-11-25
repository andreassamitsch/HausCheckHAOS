#!/bin/sh
set -eu

# Music, catalog and authenticated Ingress remain online.
# Firefox, Xvfb and VNC are now launched only by an explicit Login button.
# The LoginBrowser manager shuts them down after session capture or idle time.
export HOME=/data
mkdir -p /data/ytmusic_auth_browser
chmod 700 /data/ytmusic_auth_browser

# Automatic video-bound proof-of-origin tokens; private to this container.
# Never publish port 4416. The provider is required only for YouTube extraction.
python -u - <<'PY' &
import logging
import re
import signal
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pot_provider")
proc = subprocess.Popen(
    ["/usr/local/bin/node", "build/main.js", "--host", "127.0.0.1", "--port", "4416"],
    cwd="/opt/bgutil/server", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, errors="replace", bufsize=1)
def stop(signum, frame):
    if proc.poll() is None:
        proc.terminate()
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
log.info("pot_provider_process_started")
# Upstream messages can contain tokens or URLs. Never log raw lines.
for line in proc.stdout:
    value = line.lower()
    reasons = []
    if any(x in value for x in ("listening", "server started", "server running")):
        reasons.append("listening")
    if any(x in value for x in ("error", "failed", "exception", "fatal", "warn", "refused", "timeout")):
        for label, patterns in (
            ("module_missing", ("cannot find module", "module not found", "err_module_not_found")),
            ("connection_refused", ("econnrefused", "connection refused")),
            ("timeout", ("timeout", "timed out")),
            ("tls_error", ("certificate", "tls", "ssl")),
            ("dns_error", ("getaddrinfo", "enotfound")),
            ("token_generation_failed", ("token", "integrity", "botguard")),
            ("dependency_error", ("not a function", "not defined", "syntaxerror", "typeerror")),
            ("address_in_use", ("eaddrinuse", "address already in use")),
        ):
            if any(x in value for x in patterns):
                reasons.append(label)
        reasons.extend("http_" + code for code in re.findall(r"\b(?:http(?: error| status)?[ :]+|status(?: code)?[ :=]+)([45][0-9]{2})\b", value))
        log.warning("pot_provider_event reason=%s", ",".join(dict.fromkeys(reasons)) or "unclassified_error")
    elif reasons:
        log.info("pot_provider_event reason=%s", ",".join(reasons))
log.warning("pot_provider_process_exited code=%s", proc.wait())
PY

python -u /app/auth_ui.py &
exec python -u /app/server.py
