from __future__ import annotations

from app.main import app
from app.analysis_package import register_analysis_package
from app.chatgpt_api import register_chatgpt_api
from app.house_manage import register_house_management

register_chatgpt_api(app)
register_analysis_package(app)
register_house_management(app)
