from __future__ import annotations

import app.mobile_first_ui as mobile_first_ui
import app.modern_ui as modern_ui


_PATCH_MARKER = "hc-mobile-interaction-fix-v1"

COMPACT_FILTER_CSS = r"""
<style id="hc-mobile-interaction-fix-v1">
/* Geschlossener Filter ist nur ein kompakter Chip statt einer breiten Karte. */
.filter-panel:not([open]) {
  display:inline-block;
  width:auto;
  max-width:100%;
  margin:0 0 12px;
  padding:0;
  overflow:visible;
  border:0;
  border-radius:0;
  background:transparent;
  box-shadow:none;
}
.filter-panel:not([open]):hover { border-color:transparent; }
.filter-panel:not([open])>summary {
  width:max-content;
  max-width:100%;
  min-height:34px;
  padding:5px 9px;
  border:1px solid var(--border);
  border-radius:999px;
  background:rgba(23,33,43,.82);
}
.filter-panel:not([open])>summary:after {
  margin-left:1px;
  font-size:13px;
}
.filter-summary {
  gap:6px;
  min-width:0;
  max-width:100%;
  font-size:12px;
}
.filter-summary svg {
  width:15px!important;
  height:15px!important;
  min-width:15px;
  flex:none;
}
.filter-summary strong {
  font-size:12px;
  line-height:1.2;
}
.filter-panel:not([open]) .filter-summary .muted { display:none; }

/* Geöffnet bleibt der Filter ein gut bedienbares, vollbreites Formular. */
.filter-panel[open] {
  display:block;
  width:100%;
  margin:0 0 14px;
  padding:0;
  overflow:hidden;
  border:1px solid var(--border);
  border-radius:14px;
  background:linear-gradient(180deg,rgba(23,33,43,.97),rgba(17,24,32,.97));
}
.filter-panel[open]>summary {
  width:100%;
  min-height:42px;
  padding:8px 11px;
  align-items:flex-start;
}
.filter-panel[open] .filter-summary {
  width:100%;
  flex-wrap:wrap;
  align-items:flex-start;
}
.filter-panel[open] .filter-summary .muted {
  flex:1 1 100%;
  width:100%;
  overflow:visible;
  text-overflow:clip;
  white-space:normal;
  overflow-wrap:anywhere;
}

/* Mobile-first: Texte dürfen sich verbreitern und umbrechen, aber nie abgeschnitten werden. */
html,body { max-width:100%; overflow-x:hidden; }
.app-header-inner,.app-main,.page-heading,.card,.house-card,.house-card-content,
.filter-panel,.filter-body,.filter-grid,.filter-grid>*,.facts-grid,.fact,
.section-title,.source-card,.notice,.object-heading { min-width:0; }
.app-title {
  overflow:visible;
  text-overflow:clip;
  white-space:normal;
  overflow-wrap:anywhere;
  line-height:1.2;
  text-align:right;
}
.page-heading h1,.house-card h3,.house-card-title,.object-heading h1,
.house-card-content>.muted,.fact-value,.source-card,.notice {
  max-width:100%;
  overflow:visible;
  text-overflow:clip;
  white-space:normal;
  overflow-wrap:anywhere;
  word-break:normal;
}
.pill {
  max-width:100%;
  white-space:normal;
  overflow-wrap:anywhere;
  text-align:left;
}
.button,button {
  max-width:100%;
  white-space:normal;
  text-align:center;
}
.detail-toolbar .button,.detail-toolbar button { white-space:nowrap; }

/* Touch-Gesten bleiben innerhalb der Lightbox. */
.hc-lightbox-stage {
  touch-action:none;
  overscroll-behavior:contain;
}

@media (max-width:599px) {
  .app-header-inner {
    min-height:58px;
    padding-top:7px;
    padding-bottom:7px;
    align-items:flex-start;
  }
  .app-brand { padding-top:3px; }
  .app-title {
    max-width:58%;
    font-size:12px;
  }
  .house-card h3 {
    font-size:17px;
    line-height:1.3;
  }
  .filter-actions {
    grid-template-columns:1fr;
  }
  .filter-actions .button,
  .filter-actions button {
    width:100%;
  }
}
</style>
<script id="hc-dashboard-filter-state-v1">
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
    if (!panel || !grid) return;

    const current = normalizedSearch(new URLSearchParams(window.location.search));
    if (current) {
      try { window.localStorage.setItem(storageKey, current); } catch (_) {}
    } else {
      let saved = '';
      try { saved = window.localStorage.getItem(storageKey) || ''; } catch (_) {}
      if (saved) {
        window.location.replace(`${window.location.pathname}${saved}${window.location.hash}`);
        return;
      }
    }

    const form = panel.querySelector('form[method="get"]');
    if (form) {
      form.addEventListener('submit', () => {
        const next = normalizedSearch(new URLSearchParams(new FormData(form)));
        try {
          if (next) window.localStorage.setItem(storageKey, next);
          else window.localStorage.removeItem(storageKey);
        } catch (_) {}
      });
    }

    panel.querySelectorAll('.filter-actions a').forEach(link => {
      link.addEventListener('click', () => {
        try { window.localStorage.removeItem(storageKey); } catch (_) {}
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

SWIPE_SCRIPT = r"""
<script id="hc-lightbox-swipe-v1">
(() => {
  const stage = document.getElementById('hc-lightbox-stage');
  const image = document.getElementById('hc-lightbox-image');
  const previous = document.getElementById('hc-lightbox-prev');
  const next = document.getElementById('hc-lightbox-next');
  if (!stage || !image || !previous || !next || stage.dataset.swipeReady === 'true') return;
  stage.dataset.swipeReady = 'true';

  let tracking = false;
  let pinching = false;
  let startX = 0;
  let startY = 0;
  let startTime = 0;

  const currentScale = () => {
    const match = String(image.style.transform || '').match(/scale\(([0-9.]+)\)/);
    return match ? Number(match[1]) : 1;
  };

  stage.addEventListener('touchstart', event => {
    if (event.touches.length > 1) {
      tracking = false;
      pinching = true;
      return;
    }
    if (event.touches.length !== 1 || currentScale() > 1.02) {
      tracking = false;
      return;
    }
    const target = event.target;
    if (target instanceof Element && target.closest('button')) {
      tracking = false;
      return;
    }
    const touch = event.touches[0];
    tracking = true;
    pinching = false;
    startX = touch.clientX;
    startY = touch.clientY;
    startTime = performance.now();
  }, {passive: true});

  stage.addEventListener('touchmove', event => {
    if (event.touches.length > 1) {
      tracking = false;
      pinching = true;
      return;
    }
    if (!tracking || event.touches.length !== 1) return;
    const touch = event.touches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) event.preventDefault();
  }, {passive: false});

  stage.addEventListener('touchend', event => {
    if (pinching) {
      if (event.touches.length === 0) pinching = false;
      tracking = false;
      return;
    }
    if (!tracking || !event.changedTouches.length || currentScale() > 1.02) {
      tracking = false;
      return;
    }
    const touch = event.changedTouches[0];
    const dx = touch.clientX - startX;
    const dy = touch.clientY - startY;
    const duration = performance.now() - startTime;
    const threshold = Math.max(44, Math.min(90, stage.clientWidth * 0.13));
    tracking = false;

    if (duration <= 900 && Math.abs(dx) >= threshold && Math.abs(dx) > Math.abs(dy) * 1.2) {
      if (dx < 0) next.click();
      else previous.click();
    }
  }, {passive: true});

  stage.addEventListener('touchcancel', () => {
    tracking = false;
    pinching = false;
  }, {passive: true});
})();
</script>
"""


def register_mobile_interaction_fix() -> None:
    if _PATCH_MARKER not in modern_ui.MODERN_CSS:
        modern_ui.MODERN_CSS += COMPACT_FILTER_CSS

    current = mobile_first_ui._lightbox_html
    if getattr(current, "_touch_swipe_patched", False):
        return

    def lightbox_with_swipe() -> str:
        return current() + SWIPE_SCRIPT

    setattr(lightbox_with_swipe, "_touch_swipe_patched", True)
    mobile_first_ui._lightbox_html = lightbox_with_swipe
