from __future__ import annotations

from app.main import app
from app.chatgpt_api import register_chatgpt_api

register_chatgpt_api(app)
