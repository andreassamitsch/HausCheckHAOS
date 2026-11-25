# MCP Diagnostics

A deliberately restricted connectivity diagnostic app, not an interactive terminal. Only two predefined TCP connections (1516, 26101) to an administrator-configured private IPv4 address. No shell execution, authentication attempts, service interrogation, file mounts, HA tokens, host networking, public port mappings, arbitrary destinations or microphone access.

Install from the existing repository. Configure target_ip locally in the app settings and start manually. GET /health shows configuration status; GET /api/soundbar/tcp performs the two fixed checks. Ingress only, restricted to Supervisor source address. Rate limit 10 seconds. Stop/uninstall from the app UI.

TCP reachability does not establish protocol identity or permission to install software. No device addresses belong in the repository. Compatibility with the HA-MCP ingress proxy must be verified after installation.

Reference: https://contributors.home-assistant.io/apps/guides/ingress/
