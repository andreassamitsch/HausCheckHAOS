from __future__ import annotations

from app.main import app
from app.analysis_package import register_analysis_package
from app.chatgpt_api import register_chatgpt_api
from app.dashboard_automation_ui import register_dashboard_automation_ui
from app.github_auto_import import register_github_auto_import
from app.github_b64_export import register_github_b64_export
from app.github_exchange import register_github_exchange
from app.gmail_exchange import register_gmail_exchange
from app.house_manage import register_house_management
from app.import_patch import register_import_patch
from app.pipeline_integration import register_pipeline_integration
from app.pipeline_status import ensure_pipeline_schema
from app.product_ui import register_product_ui
from app.product_ui_fix import register_product_ui_fix
from app.search_automation import register_search_automation
from app.search_automation_ui import register_search_automation_ui
from app.search_ui_patch import register_search_profile_patch
from app.storage import init_storage
from app.valuation_schema import register_valuation_schema
from app.valuation_ui import register_valuation_ui

# Erweiterungsmodule führen bereits bei der Registrierung Schema-Migrationen aus.
# Deshalb muss die Basisdatenbank auch bei einer frischen Installation vorher existieren.
init_storage()
ensure_pipeline_schema()
register_valuation_schema()
register_chatgpt_api(app)
register_analysis_package(app)
register_house_management(app)
register_search_profile_patch(app)
register_github_exchange(app)
register_pipeline_integration(app)
register_gmail_exchange(app)
register_github_b64_export(app)
register_import_patch(app)
register_github_auto_import(app)
register_search_automation(app)
# Muss zuletzt registriert werden: ersetzt die technischen Zwischen-UIs durch die Produktansicht.
register_product_ui(app)
register_product_ui_fix(app)
# Automatik-Einstellungen ersetzen abschließend die vorbereitende Suchprofil-UI aus v0.6.0.
register_search_automation_ui(app)
register_dashboard_automation_ui(app)
# Formatiert Zeiten lokal und erweitert die Hausansicht um KI-Kaufpreis und Investitionsposten.
register_valuation_ui(app)
