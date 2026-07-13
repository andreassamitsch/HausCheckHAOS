from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

import app.dashboard_automation_ui as dashboard_automation_ui
import app.focused_ui as focused_ui
import app.main as main
import app.modern_ui as modern_ui
import app.product_ui as product_ui
import app.search_automation_ui as search_automation_ui
import app.search_lifecycle_ui as search_lifecycle_ui


APP_ROUTE_MARKERS = (
    "/houses/",
    "/search",
    "/settings",
    "/rejected",
    "/import",
    "/media/",
    "/github",
    "/manual",
    "/chatgpt",
)

EXTRA_CSS = """
<style>
  .app-header-actions { display:flex; align-items:center; gap:8px; margin-left:8px; }
  .app-header-refresh { background:transparent!important; border-color:var(--border)!important; }
  .app-header-refresh:hover { background:var(--surface-3)!important; }
  .detail-toolbar .page-reload { background:var(--surface-3); border-color:#344758; }
  @media (max-width:520px) {
    .app-title { display:none; }
    .app-header-actions { margin-left:auto; }
  }
</style>
"""

INGRESS_LINK_SCRIPT = r"""
<script id="hauscheck-ingress-link-fix">
(() => {
  const markers = ["/houses/", "/search", "/settings", "/rejected", "/import", "/media/", "/github", "/manual", "/chatgpt"];
  const pathname = window.location.pathname.replace(/\/+$/, "");
  let markerIndex = -1;
  for (const marker of markers) {
    const index = pathname.indexOf(marker);
    if (index >= 0 && (markerIndex < 0 || index < markerIndex)) markerIndex = index;
  }
  const appRoot = markerIndex >= 0 ? pathname.slice(0, markerIndex) : pathname;
  const appRoute = markerIndex >= 0 ? (pathname.slice(markerIndex) || "/") : "/";

  function isExternal(raw) {
    return /^(?:https?:|mailto:|tel:|javascript:|data:|blob:)/i.test(raw) || raw.startsWith("//") || raw.startsWith("#");
  }

  function appUrl(raw) {
    const value = raw == null ? "" : String(raw).trim();
    if (isExternal(value)) return value;
    if (value === "") return appRoot + appRoute + window.location.search + window.location.hash;
    const resolved = new URL(value, "https://hauscheck.invalid" + appRoute);
    return appRoot + resolved.pathname + resolved.search + resolved.hash;
  }

  document.querySelectorAll("a[href]").forEach((node) => {
    const raw = node.getAttribute("href");
    if (raw != null && !isExternal(raw.trim())) node.setAttribute("href", appUrl(raw));
  });
  document.querySelectorAll("form[action]").forEach((node) => {
    const raw = node.getAttribute("action");
    if (raw != null && !isExternal(raw.trim())) node.setAttribute("action", appUrl(raw));
  });
  document.querySelectorAll("img[src], source[src]").forEach((node) => {
    const raw = node.getAttribute("src");
    if (raw != null && !isExternal(raw.trim())) node.setAttribute("src", appUrl(raw));
  });

  window.hauscheckAppRoot = appRoot;
  window.hauscheckAppUrl = appUrl;
})();
</script>
"""


def detect_app_root(pathname: str) -> tuple[str, str]:
    path = str(pathname or "").rstrip("/")
    positions = [index for marker in APP_ROUTE_MARKERS if (index := path.find(marker)) >= 0]
    if not positions:
        return path, "/"
    index = min(positions)
    return path[:index], path[index:] or "/"


def resolve_ingress_url(pathname: str, raw: str | None) -> str:
    value = str(raw or "").strip()
    if re.match(r"^(?:https?:|mailto:|tel:|javascript:|data:|blob:)", value, re.I) or value.startswith(("//", "#")):
        return value
    app_root, app_route = detect_app_root(pathname)
    if not value:
        return app_root + app_route
    resolved = urlsplit(urljoin("https://hauscheck.invalid" + app_route, value))
    return app_root + resolved.path + (("?" + resolved.query) if resolved.query else "") + (("#" + resolved.fragment) if resolved.fragment else "")


def _inject_refresh_button(html: str) -> str:
    button = (
        '<div class="app-header-actions">'
        '<button class="icon-button app-header-refresh" type="button" '
        'onclick="window.location.reload()" title="Aktuelle Seite neu laden" aria-label="Aktuelle Seite neu laden">'
        f'{modern_ui.icon("refresh")}</button></div>'
    )
    return re.sub(
        r'(<div class="app-title">.*?</div>)(\s*</div>\s*</header>)',
        r'\1' + button + r'\2',
        html,
        count=1,
        flags=re.S,
    )


def _rename_source_refresh(html: str) -> str:
    html = html.replace("Inseratsdaten und Medien werden aktualisiert …", "Inserat wird neu eingelesen …")
    html = html.replace("> Aktualisieren</button></form>", "> Inserat neu einlesen</button></form>")
    return html


def _decorate_response(response: HTMLResponse) -> HTMLResponse:
    html = response.body.decode("utf-8", errors="replace")
    if "hauscheck-ingress-link-fix" in html:
        return response
    html = html.replace("</head>", EXTRA_CSS + "</head>", 1)
    html = _inject_refresh_button(html)
    html = _rename_source_refresh(html)
    html = html.replace("</body>", INGRESS_LINK_SCRIPT + "</body>", 1)
    # Die ursprüngliche Content-Length passt nach der HTML-Erweiterung nicht mehr.
    # HTMLResponse berechnet sie deshalb anhand des neuen Inhalts erneut.
    headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
    return HTMLResponse(content=html, status_code=response.status_code, headers=headers)


def register_ingress_link_fix(app: FastAPI) -> None:
    base_layout = modern_ui.modern_layout

    def ingress_safe_layout(title: str, body: str, home_href: str = "./") -> HTMLResponse:
        return _decorate_response(base_layout(title, body, home_href))

    modern_ui.modern_layout = ingress_safe_layout
    main.layout = ingress_safe_layout
    for module in [
        product_ui,
        focused_ui,
        search_lifecycle_ui,
        search_automation_ui,
        dashboard_automation_ui,
    ]:
        if hasattr(module, "layout"):
            module.layout = ingress_safe_layout
