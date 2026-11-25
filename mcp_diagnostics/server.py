"""Fixed-purpose HA Ingress diagnostic service; no shell, arbitrary URL or command execution."""
import ipaddress
import json
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORTS = (1516, 26101)
ALLOWED_NETWORKS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"))
SUPERVISOR_IP = "172.30.32.2"

def validated_target(raw):
    try:
        addr = ipaddress.IPv4Address(raw)
    except (ValueError, TypeError):
        return None
    if not any(addr in net for net in ALLOWED_NETWORKS):
        return None
    if addr in ipaddress.ip_network("172.30.32.0/23"):
        return None
    return str(addr)

def probe(target):
    if validated_target(target) != target:
        raise ValueError("Invalid target")
    results = []
    for port in PORTS:
        started = time.monotonic()
        try:
            with socket.create_connection((target, port), timeout=2):
                status = "open"
        except ConnectionRefusedError:
            status = "refused"
        except TimeoutError:
            status = "timeout"
        except OSError:
            status = "unreachable"
        results.append({"port": port, "status": status, "elapsed_ms": round((time.monotonic()-started)*1000)})
    return results

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.client_address[0] != SUPERVISOR_IP:
            return self.reply(403, {"error": "Ingress only"})
        if self.path in ("/", "/health"):
            return self.reply(200, {"service": "mcp_diagnostics", "configured": bool(self.server.target), "ports": PORTS})
        if self.path != "/api/soundbar/tcp":
            return self.reply(404, {"error": "Unknown endpoint"})
        if not self.server.target:
            return self.reply(409, {"error": "Configure a target in the app settings"})
        if time.monotonic() - self.server.last_probe < 10:
            return self.reply(429, {"error": "Rate limit; wait 10 seconds"})
        self.server.last_probe = time.monotonic()
        self.reply(200, {"results": probe(self.server.target)})

    def log_message(self, fmt, *args):
        # No private IP or headers in application access logs.
        pass

def main():
    options = json.loads(Path("/data/options.json").read_text())
    server = HTTPServer(("0.0.0.0", 8099), Handler)
    server.target = validated_target(options.get("target_ip", ""))
    server.last_probe = -100.0
    print("MCP Diagnostics started; target configured:", bool(server.target), flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
