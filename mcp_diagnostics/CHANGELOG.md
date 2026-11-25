# Changelog

## 0.1.2
- Run fixed connectivity check once at configured startup; publish results via existing authenticated Supervisor logs. Retain Ingress source restriction.

## 0.1.1
- Read Supervisor root-owned options at startup, then drop privileges before serving any requests.

## 0.1.0
- Initial restricted TCP connectivity diagnostics; authenticated Ingress only.
