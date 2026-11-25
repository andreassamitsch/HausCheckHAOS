# MCP Diagnostics

A deliberately restricted connectivity diagnostic app, not an interactive terminal. Only predefined TCP connectivity checks and standard SSDP/mDNS discovery to an administrator-configured private IPv4 address. No shell execution, authentication attempts, service interrogation, file mounts, HA tokens, host networking, public port mappings, arbitrary destinations or microphone access.

Install from the existing repository. Configure target_ip locally in the app settings and start manually. GET /health shows configuration status; GET /api/soundbar/tcp performs the two fixed checks. Ingress only, restricted to Supervisor source address. Rate limit 10 seconds. Stop/uninstall from the app UI.

TCP reachability does not establish protocol identity or permission to install software. No device addresses belong in the repository. Compatibility with the HA-MCP ingress proxy must be verified after installation.

Reference: https://contributors.home-assistant.io/apps/guides/ingress/

At startup, when configured, the app performs one bounded service inventory and prints the port/status pairs and sanitized discovery service types to its Supervisor log (no target address). HA-MCP can retrieve logs without direct access to the Ingress server. Restart explicitly to repeat; no periodic scans.

Version 0.1.3 adds a fixed 22-port inventory (four concurrent connections maximum), standard read-only SSDP and mDNS queries, and target-only reply filtering. No credentials, packet contents, instance names, private IPs or arbitrary commands are logged. Multicast queries are local; other devices' replies are discarded. Container networking can limit discovery. An open port is only a reachability observation.
