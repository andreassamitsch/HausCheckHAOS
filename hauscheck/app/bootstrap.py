from __future__ import annotations

from app.main import app
from app.analysis_freshness_ui import register_analysis_freshness_ui
from app.analysis_package import register_analysis_package
from app.blank_query_fix import register_blank_query_fix
from app.candidate_preimport_dedupe import register_candidate_preimport_dedupe
from app.chatgpt_api import register_chatgpt_api
from app.dashboard_automation_ui import register_dashboard_automation_ui
from app.dashboard_redirect_fix import register_dashboard_redirect_fix
from app.expose_address_quality import register_expose_address_quality
from app.expose_ai_export import register_expose_ai_export
from app.expose_review import register_expose_review
from app.focused_ui import register_focused_ui
from app.github_auto_import import register_github_auto_import
from app.github_exchange import register_github_exchange
from app.github_import_runtime_fix import register_github_import_runtime_fix
from app.gmail_exchange import register_gmail_exchange
from app.house_manage import register_house_management
from app.house_merge import register_house_merge
from app.immoscout_dynamic_mode import register_immoscout_dynamic_mode
from app.immoscout_dynamic_search import register_immoscout_dynamic_search
from app.immoscout_numeric_fix import register_immoscout_numeric_fix
from app.immoscout_quality import register_immoscout_quality
from app.immoscout_search_resilience import register_immoscout_search_resilience
from app.immoscout_search_resilience_compat import register_immoscout_search_resilience_compat
from app.immoscout_support import register_immoscout_support
from app.immoscout_url_runtime_fix import register_immoscout_url_runtime_fix
from app.import_patch import register_import_patch
from app.ingress_link_fix import register_ingress_link_fix
from app.live_filter_pan import register_live_filter_pan
from app.media_cleanup_policy import register_media_cleanup_policy
from app.media_cleanup_ui import register_media_cleanup_ui
from app.media_quality_v2 import register_media_quality_v2
from app.media_quality_v2_fix import register_media_quality_v2_fix
from app.media_startup_fix import register_media_startup_fix
from app.mobile_first_ui import register_mobile_first_ui
from app.mobile_interaction_fix import register_mobile_interaction_fix
from app.mobile_layout_state_fix import register_mobile_layout_state_fix
from app.modern_ui import register_modern_ui
from app.modern_ui_fix import register_modern_ui_fix
from app.parser_quality import register_parser_quality
from app.pdf_ingress_fix import register_pdf_ingress_fix
from app.peisser_dedupe_fix import register_peisser_dedupe_fix
from app.peisser_runtime_repair import register_peisser_runtime_repair
from app.peisser_support import register_peisser_support
from app.peisser_support_fix import register_peisser_support_fix
from app.pipeline_integration import register_pipeline_integration
from app.pipeline_status import ensure_pipeline_schema
from app.product_ui import register_product_ui
from app.product_ui_fix import register_product_ui_fix
from app.search_automation import register_search_automation
from app.search_automation_ui import register_search_automation_ui
from app.search_background_run import register_search_background_run
from app.search_lifecycle import register_search_lifecycle
from app.search_lifecycle_refresh import register_search_lifecycle_refresh
from app.search_lifecycle_ui import register_search_lifecycle_ui
from app.search_performance import register_search_performance
from app.search_performance_extra import register_search_performance_extra
from app.search_runtime_final import register_search_runtime_final
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
# Baut auf dem finalen Analyseimport und dem Portalsuchlauf auf.
register_search_lifecycle()
register_search_lifecycle_refresh()
register_gmail_exchange(app)
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
# Unterscheidet die letzte importierte Analyse eindeutig von einem neu ausstehenden Lauf.
register_analysis_freshness_ui(app)
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
register_expose_review(app)
# Ergänzt österreichische Dorf-/Ortsadressen und filtert Makler-Kontaktadressen.
register_expose_address_quality()
# PDFs können entfernt werden und fließen größenoptimiert in jede neue KI-Bewertung ein.
register_expose_ai_export(app)
# PDF-Links bleiben im authentifizierten Home-Assistant-Ingress; Download separat möglich.
register_pdf_ingress_fix(app)
# ImmobilienScout24-Suche, strukturierter Exposé-Parser und automatische Duplikatzuordnung.
register_immoscout_support(app)
# Nur hochsichere Quellen-/Fakten-/Bildtreffer werden automatisch zusammengeführt.
register_immoscout_quality(app)
# Such-URLs für ImmobilienScout und Willhaben werden aus PLZ und Profilfiltern erzeugt.
register_immoscout_dynamic_search(app)
# Eigene Spezial-URLs bleiben erhalten; Standardprofile werden weiterhin dynamisch erzeugt.
register_immoscout_dynamic_mode(app)
# Dezimalwerte bleiben bei wiederholtem Speichern stabil; beschädigte Profile werden repariert.
register_immoscout_numeric_fix(app)
# ImmobilienScout-Parameter werden ohne .0 gespeichert und mit Browser-Headern geladen.
register_immoscout_url_runtime_fix(app)
# Suchseiten werden als Browser-Session, direkt und als Crawler abgerufen; codierte Exposé-Links werden erkannt.
register_immoscout_search_resilience(app)
# Willhaben bleibt unverändert; nur sichtbare Leermeldungen gelten als echte 0 Treffer.
register_immoscout_search_resilience_compat(app)
# Peisser: Seiten 1 bis 10, lokale Filter, Detail-/Text-/Galerieparser und verkaufte Objekte ausschließen.
register_peisser_support(app)
register_peisser_support_fix(app)
# Peisser führt die sichere Cross-Portal-Prüfung vor Rückgabe der Kandidatenliste aus.
register_peisser_dedupe_fix(app)
# Sichere Duplikate werden vor der Kandidatenanzeige bestehenden Hausakten zugeordnet und aktualisiert.
register_candidate_preimport_dedupe(app)
# Finale Peisser-Reparatur: faktenbasierte Zuordnung ohne veraltete Bilder/Titel und korrekte Portalmetadaten.
register_peisser_runtime_repair(app)
# Konservative Vergleichsregeln müssen vor der Medienregistrierung aktiv sein.
register_media_quality_v2_fix()
# Der alte Bestandslauf bleibt deaktiviert; keine automatische Bereinigung beim oder nach dem Start.
register_media_startup_fix(app)
# Bereinigung nach Bildimport, stabile Galeriereihenfolge und vollständiger KI-Bildexport.
register_media_quality_v2(app)
# Der KI-Export verwendet den bereits bereinigten Bestand und startet keinen weiteren Vergleich.
register_media_cleanup_policy()
# Sichtbarer manueller Bereinigungslauf für bereits vorhandene Galerien.
register_media_cleanup_ui(app)
# GitHub-DELETE, verwaiste Ergebnisse und wiederholte Auto-Import-Fehler reparieren.
register_github_import_runtime_fix()
# Der manuelle Suchknopf startet zuletzt registriert und blockiert die Oberfläche nicht.
register_search_background_run(app)
# Gespeicherte Dashboardfilter werden ohne 307-Redirectschleife intern angewandt.
register_dashboard_redirect_fix(app)
# Finaler Suchablauf: keine Wrapper-Rekursion, gemeinsame Caches und genau eine Medienbereinigung.
register_search_performance()
# Peisser-Cache, Fakten-vor-Bilder-Prüfung und Schonpause zwischen automatischen Profilen.
register_search_performance_extra()
# Ein finaler Runner bewahrt Peisser-Lifecycle und überspringt Bildprüfung ohne Vergleichsbestand.
register_search_runtime_final()
