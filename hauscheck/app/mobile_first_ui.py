from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

import app.modern_ui as modern_ui
import app.product_ui as product_ui
from app.house_merge import preview_for_dashboard
from app.pipeline_status import get_pipeline_status
from app.storage import get_house, list_houses, list_media, list_sources
from app.ui_helpers import esc, format_datetime, house_score_html, house_score_result


MOBILE_FIRST_CSS = r"""
<style>
/* Mobile-first Grundlayout */
.app-main { width:100%; padding:14px 12px calc(92px + env(safe-area-inset-bottom)); }
.app-header-inner { min-height:58px; padding:0 12px; }
.app-title { max-width:44%; font-size:13px; }
.page-heading { display:block; margin:2px 0 14px; }
.page-heading h1 { font-size:28px; }
.page-heading .page-actions { width:100%; margin-top:12px; display:grid; grid-template-columns:1fr 1fr; }
.page-heading .page-actions .button { width:100%; }
.grid,.two-column,.house-grid { grid-template-columns:1fr; gap:12px; }
.card { padding:14px; border-radius:15px; }
.button,button { min-height:44px; }
.detail-toolbar { top:64px; margin:10px -4px 16px; padding:7px; border-radius:14px; overflow-x:auto; scrollbar-width:none; }
.detail-toolbar::-webkit-scrollbar { display:none; }
.detail-toolbar .button,.detail-toolbar button { min-height:42px; padding:9px 11px; white-space:nowrap; }
.facts-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.fact { padding:11px; }
.fact-value { font-size:16px; }
.house-card { border-radius:16px; }
.house-card-media { aspect-ratio:16/10; }
.house-card-content { padding:13px; }
.house-card-actions { display:grid; grid-template-columns:minmax(0,1fr) 44px; gap:8px; align-items:stretch; }
.house-card-actions .button { width:100%; height:44px; }
.house-card-actions form { margin:0; width:44px; height:44px; }
.house-card-actions .reject-button { width:44px!important; height:44px!important; min-height:44px!important; padding:0!important; border-radius:12px!important; background:#55252b!important; border:1px solid #8b3e48!important; color:#ffd9dd!important; }
.house-card-actions .reject-button:hover { background:#692c34!important; }
.house-card-meta { display:flex; flex-wrap:wrap; gap:4px; margin:8px 0 0; }
.house-card-time { margin-top:8px; font-size:12px; }

/* Dezenter Kandidaten-Link */
.candidate-mini { display:flex; align-items:center; gap:9px; width:max-content; max-width:100%; margin:0 0 13px; padding:7px 10px; border:1px solid var(--border); border-radius:999px; background:rgba(23,33,43,.72); color:var(--muted); text-decoration:none; font-size:13px; }
.candidate-mini strong { color:var(--text); }
.candidate-mini svg { width:16px; height:16px; flex:none; }

/* Kompakte Sortierung und Filterung */
.filter-panel { margin:0 0 14px; padding:0; overflow:hidden; }
.filter-panel>summary { min-height:46px; padding:0 13px; }
.filter-summary { display:flex; align-items:center; gap:8px; min-width:0; }
.filter-summary strong { white-space:nowrap; }
.filter-summary .muted { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.filter-panel[open]>summary { border-bottom:1px solid var(--border); }
.filter-body { padding:13px; }
.filter-grid { display:grid; grid-template-columns:1fr; gap:0 10px; }
.filter-actions { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; }
.filter-actions .button,.filter-actions button { width:100%; }
.filter-chip { display:inline-flex; min-width:24px; height:24px; align-items:center; justify-content:center; border-radius:999px; background:var(--primary-strong); color:white; font-size:12px; font-weight:800; }
.results-note { margin:0 0 10px; font-size:13px; }

/* Hausaktenkopf: Bild ohne langen Titeltext */
.object-hero { position:relative; border-radius:18px; overflow:hidden; border:1px solid var(--border); background:#0b1117; box-shadow:var(--shadow); }
.object-hero-trigger { display:block; width:100%; padding:0; border:0; border-radius:0; background:transparent; cursor:zoom-in; }
.object-hero-trigger:hover { transform:none; }
.object-hero img { display:block; width:100%; height:250px; object-fit:cover; }
.object-hero-meta { position:absolute; left:0; right:0; bottom:0; display:flex; flex-wrap:wrap; gap:6px; padding:48px 12px 11px; pointer-events:none; background:linear-gradient(transparent,rgba(4,7,10,.9)); }
.hero-meta-chip { display:inline-flex; align-items:center; min-height:29px; padding:5px 9px; border-radius:999px; background:rgba(15,22,29,.82); border:1px solid rgba(255,255,255,.16); color:#f5f8fa; font-size:12px; font-weight:750; backdrop-filter:blur(8px); }
.hero-meta-chip.location { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hero-gallery-hint { position:absolute; top:9px; right:9px; display:inline-flex; align-items:center; gap:6px; padding:7px 9px; border-radius:999px; background:rgba(8,13,18,.76); border:1px solid rgba(255,255,255,.18); color:white; font-size:12px; font-weight:700; pointer-events:none; backdrop-filter:blur(8px); }
.object-heading { padding:15px 2px 2px; }
.object-heading h1 { margin:0; font-size:26px; line-height:1.12; letter-spacing:-.03em; }
.object-heading p { margin:6px 0 0; }

/* Galerie: auf Smartphones immer zweispaltig */
.gallery-mobile { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }
.gallery-item { display:block; width:100%; min-height:0; padding:0; margin:0; border:1px solid var(--border); border-radius:11px; overflow:hidden; background:#0b1117; aspect-ratio:4/3; cursor:zoom-in; }
.gallery-item:hover { transform:none; border-color:#45657e; }
.gallery-item img { display:block; width:100%; height:100%; object-fit:cover; }

/* Lightbox statt direktem Medien-Link, damit Ingress-Autorisierung erhalten bleibt */
.hc-lightbox[hidden] { display:none!important; }
.hc-lightbox { position:fixed; inset:0; z-index:10000; display:grid; grid-template-rows:auto 1fr auto; background:rgba(2,4,7,.96); color:white; touch-action:none; }
.hc-lightbox-top { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:calc(8px + env(safe-area-inset-top)) 10px 8px; }
.hc-lightbox-title { font-size:13px; color:#c9d2d9; }
.hc-lightbox button { width:44px; height:44px; min-height:44px; padding:0; border-radius:50%; background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.16); }
.hc-lightbox-stage { position:relative; min-height:0; display:grid; place-items:center; overflow:hidden; }
.hc-lightbox-image { max-width:100%; max-height:100%; object-fit:contain; transform-origin:center center; will-change:transform; user-select:none; -webkit-user-drag:none; }
.hc-lightbox-prev,.hc-lightbox-next { position:absolute; top:50%; transform:translateY(-50%); z-index:2; }
.hc-lightbox-prev:hover,.hc-lightbox-next:hover { transform:translateY(-50%); }
.hc-lightbox-prev { left:7px; }
.hc-lightbox-next { right:7px; }
.hc-lightbox-controls { display:flex; justify-content:center; align-items:center; gap:9px; padding:9px 10px calc(10px + env(safe-area-inset-bottom)); }
.hc-lightbox-zoom { min-width:66px; text-align:center; font-size:13px; color:#d3dce2; }
body.lightbox-open { overflow:hidden; }

/* Tabellen und Formulare auf kleinen Displays */
table { display:block; max-width:100%; overflow-x:auto; }
input,textarea,select { font-size:16px; }
.merge-option { grid-template-columns:20px 66px minmax(0,1fr); }
.merge-option img { width:66px; height:54px; }
.cover-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.cover-choice img { aspect-ratio:1/1; }

@media (min-width:600px) {
  .app-main { padding:20px 18px 90px; }
  .page-heading { display:flex; align-items:flex-end; }
  .page-heading .page-actions { width:auto; margin-top:0; display:flex; }
  .filter-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .gallery-mobile { grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
  .object-hero img { height:390px; }
  .object-heading h1 { font-size:32px; }
}
@media (min-width:860px) {
  .app-main { width:min(var(--content),100%); padding:24px 20px 80px; }
  .grid { grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
  .two-column { grid-template-columns:minmax(0,1.45fr) minmax(300px,.75fr); }
  .house-grid { grid-template-columns:repeat(auto-fill,minmax(285px,1fr)); gap:16px; }
  .filter-grid { grid-template-columns:repeat(4,minmax(0,1fr)); }
  .gallery-mobile { grid-template-columns:repeat(4,minmax(0,1fr)); }
  .object-hero img { height:520px; }
  .object-heading h1 { font-size:38px; }
  .facts-grid { grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); }
}
</style>
"""


def _methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", set()) or set())


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (getattr(route, "path", "") == path and method in _methods(route))
    ]


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _ordered_images(house_id: str) -> list[dict[str, Any]]:
    house = get_house(house_id) or {}
    selected = str(house.get("preview_media_id") or "")
    portal_preview = str(house.get("preview_image_url") or "").strip()
    images = [
        item
        for item in list_media(house_id)
        if item.get("kind") == "image"
        and item.get("download_status") == "downloaded"
        and item.get("local_path")
    ]

    def rank(item: dict[str, Any]) -> tuple[int, str]:
        media_id = str(item.get("id") or "")
        original_url = str(item.get("original_url") or "").strip()
        if selected and media_id == selected:
            return (0, str(item.get("created_at") or ""))
        if not selected and portal_preview and original_url == portal_preview:
            return (1, str(item.get("created_at") or ""))
        return (2, str(item.get("created_at") or ""))

    images.sort(key=rank)
    return images


def _hero_src(house: dict[str, Any]) -> str:
    images = _ordered_images(str(house.get("id") or ""))
    selected = str(house.get("preview_media_id") or "")
    portal_preview = str(house.get("preview_image_url") or "").strip()
    if selected and images:
        return f'../media/{esc(images[0].get("id"))}'
    if portal_preview:
        for image in images:
            if str(image.get("original_url") or "").strip() == portal_preview:
                return f'../media/{esc(image.get("id"))}'
        return esc(portal_preview)
    if images:
        return f'../media/{esc(images[0].get("id"))}'
    return ""


def _score_value(house: dict[str, Any]) -> int:
    try:
        return int(house_score_result(house).get("score") or 0)
    except Exception:
        return 0


def _filter_and_sort(
    houses: list[dict[str, Any]],
    sort: str,
    q: str,
    min_score: int | None,
    max_price: int | None,
    max_hwb: float | None,
) -> list[dict[str, Any]]:
    needle = str(q or "").strip().lower()
    result: list[dict[str, Any]] = []
    for house in houses:
        searchable = " ".join(
            str(house.get(key) or "")
            for key in ("title", "location_text", "heating", "notes")
        ).lower()
        if needle and needle not in searchable:
            continue
        if min_score is not None and _score_value(house) < min_score:
            continue
        price = _number(house.get("price_eur"))
        if max_price is not None and (price is None or price > max_price):
            continue
        hwb = _number(house.get("energy_hwb"))
        if max_hwb is not None and (hwb is None or hwb > max_hwb):
            continue
        result.append(house)

    def num_key(field: str, reverse_missing: bool = False):
        def key(house: dict[str, Any]) -> tuple[bool, float]:
            value = _number(house.get(field))
            return (value is None if not reverse_missing else value is not None, value or 0)
        return key

    if sort == "created_asc":
        result.sort(key=lambda item: str(item.get("created_at") or ""))
    elif sort == "score_desc":
        result.sort(key=lambda item: (_score_value(item), str(item.get("created_at") or "")), reverse=True)
    elif sort == "score_asc":
        result.sort(key=lambda item: (_score_value(item), str(item.get("created_at") or "")))
    elif sort == "location_asc":
        result.sort(key=lambda item: str(item.get("location_text") or "zzzz").lower())
    elif sort == "price_asc":
        result.sort(key=num_key("price_eur"))
    elif sort == "price_desc":
        result.sort(key=lambda item: (_number(item.get("price_eur")) is not None, _number(item.get("price_eur")) or 0), reverse=True)
    elif sort == "hwb_asc":
        result.sort(key=num_key("energy_hwb"))
    elif sort == "living_desc":
        result.sort(key=lambda item: (_number(item.get("living_area_m2")) is not None, _number(item.get("living_area_m2")) or 0), reverse=True)
    elif sort == "plot_desc":
        result.sort(key=lambda item: (_number(item.get("plot_area_m2")) is not None, _number(item.get("plot_area_m2")) or 0), reverse=True)
    else:
        result.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return result


def _house_card(house: dict[str, Any]) -> str:
    house_id = str(house.get("id") or "")
    score = house_score_result(house)
    status = get_pipeline_status(house_id)
    preview = preview_for_dashboard(house)
    return f"""
    <article class="card house-card">
      <a class="house-card-media" href="houses/{esc(house_id)}">{preview}</a>
      <div class="house-card-content">
        <a class="house-card-title" href="houses/{esc(house_id)}"><h3>{esc(house.get('title'))}</h3></a>
        <div class="muted">{esc(house.get('location_text') or 'Lage unbekannt')}</div>
        <div class="house-card-meta">
          <span class="pill {esc(score.get('pill'))}">{'KI' if score.get('source') == 'ai' else 'Vorprüfung'} {esc(score.get('score'))}/100</span>
          {product_ui._pipeline_badge(status)}
          <span class="pill">{modern_ui.main.money(house.get('price_eur'))}</span>
          <span class="pill">{modern_ui.main.num(house.get('living_area_m2'),' m² Wfl.')}</span>
          <span class="pill">{modern_ui.main.num(house.get('plot_area_m2'),' m² Grund')}</span>
          <span class="pill">HWB {modern_ui.main.num(house.get('energy_hwb'))}</span>
        </div>
        <div class="muted house-card-time">Importiert: {esc(format_datetime(house.get('created_at')))}</div>
        <div class="house-card-actions">
          <a class="button secondary" href="houses/{esc(house_id)}">Hausakte öffnen</a>
          <form class="reject-form" method="post" action="houses/{esc(house_id)}/reject" data-no-loading="true" onsubmit="return confirm('Dieses Objekt als abgelehnt markieren?');">
            <button class="reject-button" type="submit" title="Ablehnen" aria-label="Ablehnen">{modern_ui.icon('trash')}</button>
          </form>
        </div>
      </div>
    </article>
    """


def _filter_panel(
    sort: str,
    q: str,
    min_score: int | None,
    max_price: int | None,
    max_hwb: float | None,
) -> str:
    sort_labels = {
        "created_desc": "neueste zuerst",
        "created_asc": "älteste zuerst",
        "score_desc": "beste Bewertung",
        "score_asc": "niedrigste Bewertung",
        "location_asc": "Ort A–Z",
        "price_asc": "Preis aufsteigend",
        "price_desc": "Preis absteigend",
        "hwb_asc": "bester HWB",
        "living_desc": "größte Wohnfläche",
        "plot_desc": "größtes Grundstück",
    }
    active_filters = sum(
        1
        for value in (str(q or "").strip(), min_score, max_price, max_hwb)
        if value not in (None, "")
    )
    options = "".join(
        f'<option value="{esc(value)}" {"selected" if sort == value else ""}>{esc(label)}</option>'
        for value, label in sort_labels.items()
    )
    open_attr = "open" if active_filters else ""
    chip = f'<span class="filter-chip">{active_filters}</span>' if active_filters else ""
    return f"""
    <details class="card filter-panel" {open_attr}>
      <summary>
        <span class="filter-summary">{modern_ui.icon('settings')}<strong>Sortieren & filtern</strong>{chip}<span class="muted">{esc(sort_labels.get(sort, sort_labels['created_desc']))}</span></span>
      </summary>
      <div class="filter-body">
        <form method="get" action="">
          <div class="filter-grid">
            <div><label>Sortierung</label><select name="sort">{options}</select></div>
            <div><label>Ort, Titel oder Heizung</label><input name="q" value="{esc(q)}" placeholder="z. B. Eibiswald"></div>
            <div><label>Mindestbewertung</label><input name="min_score" type="number" min="0" max="100" value="{esc(min_score if min_score is not None else '')}" placeholder="z. B. 70"></div>
            <div><label>Maximalpreis €</label><input name="max_price" type="number" min="0" value="{esc(max_price if max_price is not None else '')}" placeholder="z. B. 380000"></div>
            <div><label>HWB maximal</label><input name="max_hwb" type="number" min="0" step="0.1" value="{esc(max_hwb if max_hwb is not None else '')}" placeholder="z. B. 150"></div>
          </div>
          <div class="filter-actions"><button type="submit">Anwenden</button><a class="button ghost" href="./">Zurücksetzen</a></div>
        </form>
      </div>
    </details>
    """


def _gallery_html(house_id: str) -> str:
    images = _ordered_images(house_id)
    if not images:
        return '<div class="card empty-state"><p class="muted">Noch keine Bilder vorhanden.</p></div>'
    return '<div class="gallery-mobile">' + ''.join(
        f'<button class="gallery-item js-lightbox" type="button" aria-label="Bild öffnen"><img src="../media/{esc(item.get("id"))}" alt="Hausbild" loading="lazy"></button>'
        for item in images
    ) + '</div>'


def _lightbox_html() -> str:
    return f"""
    <div id="hc-lightbox" class="hc-lightbox" hidden role="dialog" aria-modal="true" aria-label="Bildergalerie">
      <div class="hc-lightbox-top">
        <span id="hc-lightbox-title" class="hc-lightbox-title">Bild</span>
        <button id="hc-lightbox-close" type="button" aria-label="Schließen">×</button>
      </div>
      <div id="hc-lightbox-stage" class="hc-lightbox-stage">
        <button id="hc-lightbox-prev" class="hc-lightbox-prev" type="button" aria-label="Vorheriges Bild">‹</button>
        <img id="hc-lightbox-image" class="hc-lightbox-image" alt="Vergrößertes Hausbild" draggable="false">
        <button id="hc-lightbox-next" class="hc-lightbox-next" type="button" aria-label="Nächstes Bild">›</button>
      </div>
      <div class="hc-lightbox-controls">
        <button id="hc-zoom-out" type="button" aria-label="Verkleinern">−</button>
        <span id="hc-zoom-value" class="hc-lightbox-zoom">100 %</span>
        <button id="hc-zoom-in" type="button" aria-label="Vergrößern">＋</button>
        <button id="hc-zoom-reset" type="button" aria-label="Zoom zurücksetzen">1:1</button>
      </div>
    </div>
    <script>
    (() => {{
      const triggers=[...document.querySelectorAll('.js-lightbox')];
      const box=document.getElementById('hc-lightbox');
      if(!box || !triggers.length) return;
      const image=document.getElementById('hc-lightbox-image');
      const title=document.getElementById('hc-lightbox-title');
      const zoomValue=document.getElementById('hc-zoom-value');
      let sources=[];
      let index=0;
      let scale=1;
      let touchDistance=0;
      let touchScale=1;

      const refreshSources=()=>{{
        sources=[];
        triggers.forEach(trigger=>{{
          const img=trigger.querySelector('img');
          const src=img ? (img.currentSrc || img.src) : '';
          if(src && !sources.includes(src)) sources.push(src);
        }});
      }};
      const applyScale=()=>{{
        scale=Math.max(1,Math.min(4,scale));
        image.style.transform=`scale(${{scale}})`;
        zoomValue.textContent=`${{Math.round(scale*100)}} %`;
      }};
      const show=(nextIndex)=>{{
        refreshSources();
        if(!sources.length) return;
        index=(nextIndex+sources.length)%sources.length;
        scale=1;
        image.style.transform='scale(1)';
        image.src=sources[index];
        title.textContent=`Bild ${{index+1}} von ${{sources.length}}`;
        zoomValue.textContent='100 %';
      }};
      const open=(src)=>{{
        refreshSources();
        index=Math.max(0,sources.indexOf(src));
        show(index);
        box.hidden=false;
        document.body.classList.add('lightbox-open');
      }};
      const close=()=>{{ box.hidden=true; document.body.classList.remove('lightbox-open'); image.removeAttribute('src'); }};

      triggers.forEach(trigger=>trigger.addEventListener('click',()=>{{
        const img=trigger.querySelector('img');
        if(img) open(img.currentSrc || img.src);
      }}));
      document.getElementById('hc-lightbox-close').addEventListener('click',close);
      document.getElementById('hc-lightbox-prev').addEventListener('click',()=>show(index-1));
      document.getElementById('hc-lightbox-next').addEventListener('click',()=>show(index+1));
      document.getElementById('hc-zoom-in').addEventListener('click',()=>{{scale+=.25;applyScale();}});
      document.getElementById('hc-zoom-out').addEventListener('click',()=>{{scale-=.25;applyScale();}});
      document.getElementById('hc-zoom-reset').addEventListener('click',()=>{{scale=1;applyScale();}});
      document.getElementById('hc-lightbox-stage').addEventListener('wheel',event=>{{event.preventDefault();scale+=event.deltaY<0?.2:-.2;applyScale();}},{{passive:false}});
      document.getElementById('hc-lightbox-stage').addEventListener('click',event=>{{if(event.target.id==='hc-lightbox-stage') close();}});
      document.getElementById('hc-lightbox-stage').addEventListener('touchstart',event=>{{
        if(event.touches.length===2){{
          const [a,b]=event.touches;
          touchDistance=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
          touchScale=scale;
        }}
      }},{{passive:true}});
      document.getElementById('hc-lightbox-stage').addEventListener('touchmove',event=>{{
        if(event.touches.length===2 && touchDistance){{
          event.preventDefault();
          const [a,b]=event.touches;
          const distance=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
          scale=touchScale*(distance/touchDistance);
          applyScale();
        }}
      }},{{passive:false}});
      document.addEventListener('keydown',event=>{{
        if(box.hidden) return;
        if(event.key==='Escape') close();
        if(event.key==='ArrowLeft') show(index-1);
        if(event.key==='ArrowRight') show(index+1);
        if(event.key==='+'){{scale+=.25;applyScale();}}
        if(event.key==='-'){{scale-=.25;applyScale();}}
      }});
    }})();
    </script>
    """


def register_mobile_first_ui(app: FastAPI) -> None:
    if "candidate-mini" not in modern_ui.MODERN_CSS:
        modern_ui.MODERN_CSS += MOBILE_FIRST_CSS

    # Auch Titelbild- und Zusammenführungsseiten verwenden dadurch zuerst das Portal-Titelbild.
    modern_ui._house_images = _ordered_images

    _remove_route(app, "/", "GET")
    _remove_route(app, "/houses/{house_id}", "GET")

    @app.get("/", response_class=HTMLResponse)
    def mobile_dashboard(
        sort: str = "created_desc",
        q: str = "",
        min_score: int | None = None,
        max_price: int | None = None,
        max_hwb: float | None = None,
    ) -> HTMLResponse:
        houses = [house for house in list_houses() if str(house.get("status") or "new") != "rejected"]
        filtered = _filter_and_sort(houses, sort, q, min_score, max_price, max_hwb)
        candidate_count = modern_ui._candidate_count()
        candidate_link = (
            f'<a class="candidate-mini" href="search">{modern_ui.icon("search")}<strong>{candidate_count}</strong> nicht importierte Kandidaten anzeigen</a>'
            if candidate_count
            else ""
        )
        body = f"""
        <div class="page-heading">
          <div><h1>Hausakten</h1><p>{len(houses)} aktive Objekte</p></div>
          <div class="page-actions"><a class="button secondary" href="search">{modern_ui.icon('search')} Suche</a><a class="button" href="import">{modern_ui.icon('plus')} Inserat</a></div>
        </div>
        {candidate_link}
        {_filter_panel(sort, q, min_score, max_price, max_hwb)}
        <p class="muted results-note">{len(filtered)} von {len(houses)} Hausakten angezeigt</p>
        <div class="house-grid">{''.join(_house_card(house) for house in filtered) if filtered else '<div class="card empty-state"><h2>Keine passenden Hausakten</h2><p class="muted">Filter zurücksetzen oder Suche anpassen.</p></div>'}</div>
        """
        return modern_ui.modern_layout("Hausakten", body, home_href="./")

    @app.get("/houses/{house_id}", response_class=HTMLResponse)
    def mobile_house_detail(house_id: str) -> HTMLResponse:
        house = get_house(house_id)
        if not house:
            raise HTTPException(status_code=404, detail="Hausakte nicht gefunden")
        images = _ordered_images(house_id)
        hero = _hero_src(house)
        hero_button = (
            f'<button class="object-hero-trigger js-lightbox" type="button" aria-label="Galerie öffnen"><img src="{hero}" alt="Titelbild der Hausakte"><span class="hero-gallery-hint">{modern_ui.icon("image")} {len(images) or 1} Bilder</span></button>'
            if hero
            else '<div style="height:220px"></div>'
        )
        hero_html = f"""
        <div class="object-hero">
          {hero_button}
          <div class="object-hero-meta">
            <span class="hero-meta-chip location">{esc(house.get('location_text') or 'Lage unbekannt')}</span>
            <span class="hero-meta-chip">{modern_ui.main.money(house.get('price_eur'))}</span>
            <span class="hero-meta-chip">{modern_ui.main.num(house.get('living_area_m2'),' m² Wfl.')}</span>
            <span class="hero-meta-chip">{modern_ui.main.num(house.get('plot_area_m2'),' m² Grund')}</span>
            <span class="hero-meta-chip">HWB {modern_ui.main.num(house.get('energy_hwb'))}</span>
          </div>
        </div>
        <div class="object-heading"><h1>{esc(house.get('title'))}</h1></div>
        """
        sources = list_sources(house_id)
        refresh_info = ""
        if house.get("last_refreshed_at"):
            refresh_info = f'<p class="muted">Zuletzt aktualisiert: {esc(format_datetime(house.get("last_refreshed_at")))} · {esc(house.get("last_refresh_summary") or "")}</p>'
        body = f"""
        {hero_html}
        <div class="detail-toolbar">
          <form method="post" action="{esc(house_id)}/refresh" data-loading="Inseratsdaten und Medien werden aktualisiert …"><button type="submit">{modern_ui.icon('refresh')} Aktualisieren</button></form>
          <a class="button secondary" href="{esc(house_id)}/merge">{modern_ui.icon('merge')} Zusammenlegen</a>
          <a class="button secondary" href="{esc(house_id)}/cover">{modern_ui.icon('image')} Titelbild</a>
          <a class="button secondary" href="{esc(house_id)}/edit">{modern_ui.icon('edit')} Bearbeiten</a>
        </div>
        {refresh_info}
        <div class="two-column">
          <div>
            <div class="card"><h2>Bewertung</h2>{house_score_html(house)}</div>
            <div class="section">{product_ui.analysis_card_html(house_id)}</div>
          </div>
          <div>
            <div class="card"><h2>Eckdaten</h2>{modern_ui._facts_html(house)}</div>
            <div class="section">{product_ui.pipeline_card_html(house_id)}</div>
          </div>
        </div>
        <div class="section-title"><h2>Bilder</h2><a class="button ghost" href="{esc(house_id)}/cover">{modern_ui.icon('image')} Titelbild wählen</a></div>
        {_gallery_html(house_id)}
        <div class="section-title"><h2>Inseratsquellen</h2><span class="pill">{len(sources)} Quelle(n)</span></div>
        {modern_ui._sources_html(house_id)}
        <div class="section grid">
          <div class="card"><h2>Exposé ergänzen</h2><p class="muted">PDF hochladen und erkannte Daten, Pläne und Bilder ergänzen.</p><form method="post" action="{esc(house_id)}/expose" enctype="multipart/form-data" data-loading="Exposé wird ausgewertet …"><input type="file" name="file" accept=".pdf,application/pdf" required><button type="submit">PDF hochladen</button></form></div>
          <div class="card"><h2>Notizen</h2><p>{esc(house.get('notes') or 'Noch keine Notizen.')}</p><a class="button secondary" href="{esc(house_id)}/edit">Bearbeiten</a></div>
        </div>
        <div class="section">{product_ui.diagnostics_html(house_id)}</div>
        <div class="section card danger-zone"><details><summary><strong>Weitere Aktionen</strong></summary><p class="muted">Objekt ablehnen oder endgültig löschen.</p><div class="action-row"><form method="post" action="{esc(house_id)}/reject" data-no-loading="true" onsubmit="return confirm('Objekt als abgelehnt markieren?');"><button class="secondary" type="submit">Ablehnen</button></form><form method="post" action="{esc(house_id)}/delete" data-loading="Hausakte wird gelöscht …" onsubmit="return confirm('Hausakte inklusive aller Daten endgültig löschen?');"><button class="danger" type="submit">Endgültig löschen</button></form></div></details></div>
        {_lightbox_html()}
        """
        return modern_ui.modern_layout(str(house.get("title") or "Hausakte"), body, home_href="../../")
