from __future__ import annotations

from app.main import app
from app.analysis_package import register_analysis_package
from app.blank_query_fix import register_blank_query_fix
from app.chatgpt_api import register_chatgpt_api
from app.dashboard_automation_ui import register_dashboard_automation_ui
from app.expose_review import register_expose_review
from app.focused_ui import register_focused_ui
from app.github_auto_import import register_github_auto_import
from app.github_b64_export import register_github_b64_export
from app.github_exchange import register_github_exchange
from app.gmail_exchange import register_gmail_exchange
from app.house_manage import register_house_management
from app.house_merge import register_house_merge
from app.import_patch import register_import_patch
from app.ingress_link_fix import register_ingress_link_fix
from app.live_filter_pan import register_live_filter_pan
from app.mobile_first_ui import register_mobile_first_ui
from app.mobile_interaction_fix import register_mobile_interaction_fix
from app.mobile_layout_state_fix import register_mobile_layout_state_fix
from app.modern_ui import register_modern_ui
from app.modern_ui_fix import register_modern_ui_fix
from app.parser_quality import register_parser_quality
from app.pipeline_integration import register_pipeline_integration
from app.pipeline_status import ensure_pipeline_schema
from app.product_ui import register_product_ui
from app.product_ui_fix import register_product_ui_fix
from app.search_automation import register_search_automation
from app.search_automation_ui import register_search_automation_ui
from app.search_lifecycle import register_search_lifecycle
from app.search_lifecycle_refresh import register_search_lifecycle_refresh
from app.search_lifecycle_ui import register_search_lifecycle_ui
from app.search_ui_patch import register_search_profile_patch
from app.storage import init_storage
from app.valuation_schema import register_valuation_schema
from app.valuation_ui import register_valuation_ui

# Erweiterungsmodule führen bereits bei der Registrierung Schema-Migrationen aus.
# Deshalb muss die Basisdatenbank auch bei einer frischen Installation vorher existieren.
init_storage()
ensure_pipeline_schema()
register_parser_quality()
register_valuation_schema()
register_chatgpt_api(app)
register_analysis_package(app)
register_house_management(app)
register_search_profile_patch(app)
register_github_exchange(app)
register_pipeline_integration(app)
# Baut auf dem finalen Analyseimport und dem Willhaben-Suchlauf auf.
register_search_lifecycle()
register_search_lifecycle_refresh()
register_gmail_exchange(app)
register_github_b64_export(app)
register_import_patch(app)
register_github_auto_import(app)
register_search_automation(app)
# Ersetzt die technischen Zwischen-UIs durch die Produktansicht.
register_product_ui(app)
register_product_ui_fix(app)
register_search_automation_ui(app)
register_dashboard_automation_ui(app)
# Formatiert Zeiten lokal und erweitert die Hausansicht um KI-Kaufpreis und Investitionsposten.
register_valuation_ui(app)
# Hausakten im Fokus, Suche per Lupe, Profile unter Einstellungen und Ablehnungsarchiv.
register_focused_ui(app)
# Preisverlauf, Offline-/Wieder-online-Status, Profil löschen und Plus-Dialog.
register_search_lifecycle_ui(app)
# Zwei Makler-Inserate zusammenführen und Galeriebild als Vorschau wählen.
register_house_merge(app)
# Moderne Navigation, sichtbare Aktionen und dedizierte Merge-/Titelbild-Seiten.
register_modern_ui(app)
# Die Ingress-Auflösung wird vor den letzten Kompatibilitätsrouten registriert.
register_ingress_link_fix(app)
register_modern_ui_fix(app)
# Finale Darstellung: mobile-first, kompakte Filter und Ingress-sichere Bild-Lightbox.
register_mobile_first_ui(app)
# Leere optionale Zahlenfilter gelten als nicht gesetzt statt als ungültige Eingabe.
register_blank_query_fix(app)
# Touch-Wischen in der Lightbox und kompakter Filter-Chip.
register_mobile_interaction_fix()
# Kein horizontales Abschneiden und serverseitig persistente Übersichtfilter.
register_mobile_layout_state_fix(app)
# Filter reagieren ohne Anwenden-Schaltfläche; gezoomte Bilder lassen sich verschieben.
register_live_filter_pan()
# PDFs bleiben sichtbar; erkannte Objektadressen werden erst nach Freigabe übernommen.
# Diese Registrierung liegt absichtlich zuletzt und wird durch einen eigenen Regressionstest geprüft.
register_expose_review(app)
