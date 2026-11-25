# Changelog

## 0.1.4
- Fixed credential-free HTTP metadata checks on selected open ports. No redirects, no control requests, bounded response reads and sanitized output.

## 0.1.3
- Add bounded fixed-port inventory and SSDP/mDNS discovery at startup with target-only reply filtering; preserve Ingress restrictions and no shell access.

## 0.1.2
- Run fixed connectivity check once at configured startup; publish results via existing authenticated Supervisor logs. Retain Ingress source restriction.

## 0.1.1
- Read Supervisor root-owned options at startup, then drop privileges before serving any requests.

## 0.1.0
- Initial restricted TCP connectivity diagnostics; authenticated Ingress only.
