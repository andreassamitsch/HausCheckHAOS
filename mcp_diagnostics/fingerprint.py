"""Fixed, credential-free HTTP service metadata checks; do not follow redirects."""
import http.client
import json
import ssl

CHECKS = ((8001, False, "/api/v2/"), (8002, True, "/api/v2/"),
          (8008, False, "/setup/eureka_info"), (8080, False, "/"),
          (8443, True, "/"))

def safe_info(body):
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    device = value.get("device")
    info = {}
    if isinstance(device, dict):
        for key in ("developerMode", "TokenAuthSupport", "type", "OS"):
            item = device.get(key)
            if isinstance(item, (bool, int)) or (
                isinstance(item, str) and item.lower() in
                ("0", "1", "true", "false", "tizen", "linux", "samsung smarttv", "soundbar")):
                info[key] = item
    # Retain only presence of known metadata keys, not names, IDs, networks or tokens.
    info["known_keys"] = sorted(set(value) & {"device", "version", "capabilities", "build_version", "cast_build_revision", "device_info", "model_name", "supported"}) 
    return info

def fingerprint(target, ports):
    results = []
    for port, tls, path in CHECKS:
        if port not in ports:
            continue
        result = {"port": port, "tls": tls, "path": path}
        conn = None
        try:
            if tls:
                # Local service classification only, with no secrets and no trust
                # assigned to a self-signed certificate. Never reuse for authentication.
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection(target, port, timeout=2, context=ctx)
            else:
                conn = http.client.HTTPConnection(target, port, timeout=2)
            conn.request("GET", path, headers={"Accept": "application/json", "Connection": "close"})
            response = conn.getresponse()
            result["status"] = response.status
            content_type = (response.getheader("Content-Type") or "").lower()
            result["format"] = "json" if "json" in content_type else "html" if "html" in content_type else "xml" if "xml" in content_type else "other"
            if response.status == 200 and result["format"] == "json":
                body = response.read(32769)
                if len(body) <= 32768:
                    result["metadata"] = safe_info(body)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            result["error"] = type(exc).__name__
        finally:
            if conn is not None:
                conn.close()
        results.append(result)
    return results
