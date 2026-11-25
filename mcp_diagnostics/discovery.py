"""Bounded read-only discovery. Only configured target responses are reported."""
import concurrent.futures
import socket
import struct
import time
import re

# Conventional HTTP, media, Samsung control and developer service candidates.
# A reachable port is not a verified protocol.
PORTS = (80, 443, 554, 1400, 1516, 1900, 5000, 5353, 7000, 7100, 7676,
         8001, 8002, 8008, 8009, 8080, 8443, 9000, 9090, 9197, 26101, 55000)
MDNS_SERVICES = ("_services._dns-sd._udp.local", "_googlecast._tcp.local",
                 "_airplay._tcp.local", "_raop._tcp.local", "_http._tcp.local",
                 "_samsungmsf._tcp.local", "_spotify-connect._tcp.local")
SSDP_TYPES = ("urn:schemas-upnp-org:device:MediaRenderer:1",
              "urn:dial-multiscreen-org:service:dial:1", "upnp:rootdevice")

def tcp_one(target, port):
    started = time.monotonic()
    try:
        with socket.create_connection((target, port), timeout=1.5):
            status = "open"
    except ConnectionRefusedError:
        status = "refused"
    except TimeoutError:
        status = "timeout"
    except OSError:
        status = "unreachable"
    return {"port": port, "status": status, "elapsed_ms": round((time.monotonic()-started)*1000)}

def tcp_inventory(target):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda p: tcp_one(target, p), PORTS))

def collect_udp(target, port, packets, multicast):
    """Send only standard discovery queries; discard other devices' replies."""
    results = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        for packet in packets:
            for dest in (target, multicast):
                try:
                    sock.sendto(packet, (dest, port))
                except OSError:
                    pass
        deadline = time.monotonic() + 3.0
        while len(results) < 48:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                payload, (sender, _) = sock.recvfrom(8192)
            except (TimeoutError, OSError):
                break
            if sender == target:
                results.append(payload)
    return results

def ssdp_discover(target):
    packets = [("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
                "MAN: \"ssdp:discover\"\r\nMX: 1\r\nST: " + st + "\r\n\r\n").encode()
               for st in SSDP_TYPES]
    replies = collect_udp(target, 1900, packets, "239.255.255.250")
    found = set()
    for payload in replies:
        # Only standard service names; never publish UUID, location, or server identifiers.
        for line in payload.decode("ascii", "ignore").splitlines():
            if line.lower().startswith("st:"):
                value = line[3:].strip().lower()
                if value in {s.lower() for s in SSDP_TYPES}:
                    found.add(value)
    return {"target_replies": len(replies), "services": sorted(found)}

def mdns_query(name):
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split("."))
    return struct.pack("!6H", 0, 0, 1, 0, 0, 0) + labels + b"\0" + struct.pack("!HH", 12, 0x8001)

def dns_name(data, offset):
    """Decode bounded DNS names including compression; reject malformed packets."""
    labels = []
    resume = None
    seen = set()
    while True:
        if offset >= len(data) or offset in seen or len(seen) > 128:
            raise ValueError("invalid DNS name")
        seen.add(offset)
        length = data[offset]
        offset += 1
        if length == 0:
            return ".".join(labels).lower(), resume if resume is not None else offset
        if length & 0xC0 == 0xC0:
            if offset >= len(data):
                raise ValueError("invalid pointer")
            if resume is None:
                resume = offset + 1
            offset = ((length & 0x3F) << 8) | data[offset]
        elif length > 63 or offset + length > len(data):
            raise ValueError("invalid label")
        else:
            labels.append(data[offset:offset+length].decode("ascii", "ignore"))
            offset += length

def mdns_services(data):
    found = set()
    if len(data) < 12:
        return found
    _, flags, qd, an, ns, ar = struct.unpack_from("!6H", data)
    if not flags & 0x8000 or qd + an + ns + ar > 256:
        return found
    try:
        offset = 12
        for _ in range(qd):
            _, offset = dns_name(data, offset)
            offset += 4
        for _ in range(an + ns + ar):
            name, offset = dns_name(data, offset)
            kind, _, _, length = struct.unpack_from("!HHIH", data, offset)
            offset += 10
            if offset + length > len(data):
                break
            if kind == 12:
                service, _ = dns_name(data, offset)
                for candidate in (name, service):
                    # Only allow well-formed DNS-SD service types, not instance names.
                    if re.fullmatch(r"_[a-z0-9-]{1,32}\._(?:tcp|udp)\.local", candidate) and candidate != "_services._dns-sd._udp.local":
                        found.add(candidate)
            offset += length
    except (ValueError, struct.error):
        pass
    return found

def mdns_discover(target):
    replies = collect_udp(target, 5353, [mdns_query(s) for s in MDNS_SERVICES], "224.0.0.251")
    found = set()
    for payload in replies:
        found.update(mdns_services(payload))
    return {"target_replies": len(replies), "services": sorted(found)}

def inventory(target):
    return {"tcp": tcp_inventory(target), "ssdp": ssdp_discover(target),
            "mdns": mdns_discover(target),
            "note": "Negative discovery may reflect container multicast limitations."}
