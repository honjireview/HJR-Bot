# app/core/config.py
# -*- coding: utf-8 -*-
import os

# Токены и ключи
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or ""

# База данных
DATABASE_URL = os.getenv("DATABASE_URL") or ""

# Вебхук
# Базовый URL (например: https://my-app.up.railway.app)
WEBHOOK_BASE_URL = (os.getenv("WEBHOOK_BASE_URL") or "").strip()
if WEBHOOK_BASE_URL and not WEBHOOK_BASE_URL.startswith(("http://", "https://")):
    WEBHOOK_BASE_URL = f"https://{WEBHOOK_BASE_URL}"

# Путь вебхука (например: /webhook)
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH") or "/webhook"
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = f"/{WEBHOOK_PATH}"

# Секрет для Telegram Webhook
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or os.getenv("TELEGRAM_WEBHOOK_SECRET") or ""


# Доп. параметры (опционально)
def _to_int(v):
    try:
        return int(v) if v is not None and v != "" else None
    except Exception:
        return None


EDITORS_CHANNEL_ID = _to_int(os.getenv("EDITORS_CHANNEL_ID"))
APPEALS_CHANNEL_ID = _to_int(os.getenv("APPEALS_CHANNEL_ID"))