from __future__ import annotations

import app.mobile_first_ui as mobile_first_ui
import app.modern_ui as modern_ui


_PATCH_MARKER = "hc-live-filter-pan-v1"

LIVE_FILTER_UI = r"""
<style id="hc-live-filter-pan-v1">
/* Ohne Anwenden-Schaltfläche bleibt nur die bewusst ausgelöste Rücksetzung. */
.filter-actions {
  display:flex!important;
  justify-content:flex-end;
  align-items:center;
  gap:8px;
}
.filter-actions .button { width:auto!important; }

/* Vergrößerte Bilder können sichtbar mit Finger oder Maus verschoben werden. */
.hc-lightbox-image { cursor:zoom-in; }
.hc-lightbox-stage[data-pannable="true"] .hc-lightbox-image { cursor:grab; }
.hc-lightbox-stage[data-pan-active="true"] .hc-lightbox-image { cursor:grabbing; }
</style>
<script id="hc-dashboard-auto-filter-v1">
(() => {
  const storageKey = 'hc-dashboard-filter-state-v1';
  const stateKeys = ['sort', 'q', 'min_score', 'max_price', 'max_hwb'];

  const normalizedSearch = params => {
    const clean = new URLSearchParams();
    stateKeys.forEach(key => {
      const value = params.get(key);
      if (value !== null && String(value).trim() !== '') clean.set(key, value);
    });
    return clean.toString() ? `?${clean.toString()}` : '';
  };

  const initialize = () => {
    const panel = document.querySelector('.filter-panel');
    const grid = document.querySelector('.house-grid');
    if (!panel || !grid || panel.dataset.autoFilterReady === 'true') return;
    panel.dataset.autoFilterReady = 'true';

    const form = panel.querySelector('form[method="get"]');
    if (!form) return;

    let timer = 0;
    const apply = () => {
      window.clearTimeout(timer);
      const next = normalizedSearch(new URLSearchParams(new FormData(form)));
      const current = normalizedSearch(new URLSearchParams(window.location.search));
      try {
        if (next) window.localStorage.setItem(storageKey, next);
        else window.localStorage.removeItem(storageKey);
      } catch (_) {}
      if (next === current) return;
      window.location.assign(`${window.location.pathname}${next}${window.location.hash}`);
    };
    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(apply, 450);
    };

    form.addEventListener('submit', event => {
      event.preventDefault();
      apply();
    });
    form.querySelectorAll('select').forEach(field => {
      field.addEventListener('change', apply);
    });
    form.querySelectorAll('input').forEach(field => {
      field.addEventListener('input', schedule);
      field.addEventListener('change', apply);
      field.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          apply();
        }
      });
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, {once:true});
  } else {
    initialize();
  }
})();
</script>
"""

PAN_SCRIPT = r"""
<script id="hc-lightbox-pan-v1">
(() => {
  const stage = document.getElementById('hc-lightbox-stage');
  const image = document.getElementById('hc-lightbox-image');
  const previous = document.getElementById('hc-lightbox-prev');
  const next = document.getElementById('hc-lightbox-next');
  const zoomIn = document.getElementById('hc-zoom-in');
  const zoomOut = document.getElementById('hc-zoom-out');
  const zoomReset = document.getElementById('hc-zoom-reset');
  if (!stage || !image || stage.dataset.panReady === 'true') return;
  stage.dataset.panReady = 'true';

  let panX = 0;
  let panY = 0;
  let startX = 0;
  let startY = 0;
  let startPanX = 0;
  let startPanY = 0;
  let touchPanning = false;
  let mousePanning = false;
  let mousePointerId = null;

  const currentScale = () => {
    const match = String(image.style.transform || '').match(/scale\(([0-9.]+)\)/);
    return match ? Number(match[1]) : 1;
  };

  const clampPan = scale => {
    if (scale <= 1.02) {
      panX = 0;
      panY = 0;
      return;
    }
    const maxX = Math.max(0, (image.clientWidth * scale - stage.clientWidth) / 2);
    const maxY = Math.max(0, (image.clientHeight * scale - stage.clientHeight) / 2);
    panX = Math.max(-maxX, Math.min(maxX, panX));
    panY = Math.max(-maxY, Math.min(maxY, panY));
  };

  const applyTransform = () => {
    const scale = currentScale();
    clampPan(scale);
    image.style.transform = `translate3d(${panX}px, ${panY}px, 0) scale(${scale})`;
    stage.dataset.pannable = scale > 1.02 ? 'true' : 'false';
    if (scale <= 1.02) stage.dataset.panActive = 'false';
  };

  const resetPan = () => {
    panX = 0;
    panY = 0;
    stage.dataset.panActive = 'false';
    applyTransform();
  };

  const syncAfterZoom = () => {
    window.requestAnimationFrame(() => {
      if (currentScale() <= 1.02) {
        panX = 0;
        panY = 0;
      }
      applyTransform();
    });
  };

  const beginPan = (x, y) => {
    startX = x;
    startY = y;
    startPanX = panX;
    startPanY = panY;
    stage.dataset.panActive = 'true';
  };

  const movePan = (x, y) => {
    panX = startPanX + (x - startX);
    panY = startPanY + (y - startY);
    applyTransform();
  };

  stage.addEventListener('touchstart', event => {
    if (event.touches.length !== 1 || currentScale() <= 1.02) {
      touchPanning = false;
      return;
    }
    const target = event.target;
    if (target instanceof Element && target.closest('button')) return;
    const touch = event.touches[0];
    touchPanning = true;
    beginPan(touch.clientX, touch.clientY);
  }, {passive:true});

  stage.addEventListener('touchmove', event => {
    if (event.touches.length === 2) {
      touchPanning = false;
      panX = 0;
      panY = 0;
      applyTransform();
      return;
    }
    if (!touchPanning || event.touches.length !== 1 || currentScale() <= 1.02) return;
    event.preventDefault();
    const touch = event.touches[0];
    movePan(touch.clientX, touch.clientY);
  }, {passive:false});

  const finishTouchPan = () => {
    touchPanning = false;
    stage.dataset.panActive = 'false';
  };
  stage.addEventListener('touchend', finishTouchPan, {passive:true});
  stage.addEventListener('touchcancel', finishTouchPan, {passive:true});

  stage.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'mouse' || event.button !== 0 || currentScale() <= 1.02) return;
    const target = event.target;
    if (target instanceof Element && target.closest('button')) return;
    mousePanning = true;
    mousePointerId = event.pointerId;
    stage.setPointerCapture(event.pointerId);
    beginPan(event.clientX, event.clientY);
    event.preventDefault();
  });

  stage.addEventListener('pointermove', event => {
    if (!mousePanning || event.pointerId !== mousePointerId) return;
    movePan(event.clientX, event.clientY);
    event.preventDefault();
  });

  const finishMousePan = event => {
    if (!mousePanning || event.pointerId !== mousePointerId) return;
    mousePanning = false;
    mousePointerId = null;
    stage.dataset.panActive = 'false';
    try { stage.releasePointerCapture(event.pointerId); } catch (_) {}
  };
  stage.addEventListener('pointerup', finishMousePan);
  stage.addEventListener('pointercancel', finishMousePan);

  [zoomIn, zoomOut].filter(Boolean).forEach(button => {
    button.addEventListener('click', syncAfterZoom);
  });
  if (zoomReset) zoomReset.addEventListener('click', () => {
    panX = 0;
    panY = 0;
    syncAfterZoom();
  });
  stage.addEventListener('wheel', syncAfterZoom, {passive:true});
  document.addEventListener('keydown', event => {
    if (event.key === '+' || event.key === '-') syncAfterZoom();
  });
  [previous, next].filter(Boolean).forEach(button => {
    button.addEventListener('click', () => {
      panX = 0;
      panY = 0;
      syncAfterZoom();
    });
  });
  image.addEventListener('load', resetPan);
  window.addEventListener('resize', applyTransform);
  applyTransform();
})();
</script>
"""


def register_live_filter_pan() -> None:
    if _PATCH_MARKER not in modern_ui.MODERN_CSS:
        modern_ui.MODERN_CSS += LIVE_FILTER_UI

    current_panel = mobile_first_ui._filter_panel
    if not getattr(current_panel, "_auto_filter_patched", False):
        def filter_panel_without_apply(*args, **kwargs) -> str:
            html = current_panel(*args, **kwargs)
            return html.replace('<button type="submit">Anwenden</button>', '')

        setattr(filter_panel_without_apply, "_auto_filter_patched", True)
        mobile_first_ui._filter_panel = filter_panel_without_apply

    current_lightbox = mobile_first_ui._lightbox_html
    if getattr(current_lightbox, "_pan_patched", False):
        return

    def lightbox_with_pan() -> str:
        return current_lightbox() + PAN_SCRIPT

    setattr(lightbox_with_pan, "_pan_patched", True)
    mobile_first_ui._lightbox_html = lightbox_with_pan
