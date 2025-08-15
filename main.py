# -*- coding: utf-8 -*-
"""
main.py — точка входа для запуска под gunicorn / Railway.
Использует модульную структуру (appealManager.py, botHandlers.py, connectionChecker.py, geminiProcessor.py и т.д.)
Безопасная фоновая установка webhook (lockfile + задержка) — НЕ выполняется синхронно при импорте.
"""

import os
import time
import logging
from threading import Thread
from typing import Optional

from flask import Flask, request, abort
import telebot

# Твоё приложение-логирование
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot")

# -------------- Обязательные переменные окружения (имена точно такие, как ты прислал) --------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_TOKEN в окружении.")

# Опциональные, но ожидаемые
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")  # если не задан — webhook не будет ставиться автоматически
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
EDITORS_CHANNEL_ID = os.getenv("EDITORS_CHANNEL_ID")
APPEALS_CHANNEL_ID = os.getenv("APPEALS_CHANNEL_ID")

# Строим URL вебхука, только если задан WEBHOOK_BASE_URL
WEBHOOK_URL: Optional[str] = None
if WEBHOOK_BASE_URL:
    WEBHOOK_BASE_URL = WEBHOOK_BASE_URL.strip().rstrip("/")
    if not (WEBHOOK_BASE_URL.startswith("http://") or WEBHOOK_BASE_URL.startswith("https://")):
        WEBHOOK_BASE_URL = "https://" + WEBHOOK_BASE_URL
    WEBHOOK_URL = f"{WEBHOOK_BASE_URL}/webhook/{TELEGRAM_TOKEN}"
else:
    log.info("WEBHOOK_BASE_URL не задан — автоматическая установка webhook пропущена.")

# -------------- Создаём bot и flask app --------------
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ----------------- Импортируем твои модули (они остаются отдельными файлами) -----------------
# Важно: эти модули не должны вызывать set_webhook при импорте!
try:
    import connectionChecker
    import botHandlers
    import appealManager
    import geminiProcessor
    import getid  # если нужен
except Exception as e:
    log.exception("Не удалось импортировать местные модули: %s", e)
    raise

# Передать/переиспользовать переменные окружения в модулях при необходимости:
# (если модули читают os.getenv сами — это не нужно, но делаю на всякий случай)
os.environ.setdefault("GEMINI_API_KEY", GEMINI_API_KEY or "")
os.environ.setdefault("DATABASE_URL", DATABASE_URL or "")
os.environ.setdefault("EDITORS_CHANNEL_ID", EDITORS_CHANNEL_ID or "")
os.environ.setdefault("APPEALS_CHANNEL_ID", APPEALS_CHANNEL_ID or "")

# Регистрируем обработчики (внутри botHandlers должен быть register_handlers)
if hasattr(botHandlers, "register_handlers"):
    botHandlers.register_handlers(bot)
else:
    log.warning("В botHandlers нет функции register_handlers(bot). Убедись, что она есть.")

# ----------------- Webhook route и healthchecks -----------------
@app.post(f"/webhook/{TELEGRAM_TOKEN}")
def telegram_webhook():
    # Telegram присылает JSON
    if request.headers.get("content-type") != "application/json":
        abort(400)
    update = telebot.types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return "ok", 200

@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def health():
    return "healthy", 200

# ----------------- Безопасная установка webhook (фон) -----------------
LOCKFILE = "/tmp/hjr_set_webhook.lock"

def _get_webhook_info_safe():
    try:
        return bot.get_webhook_info()
    except Exception as e:
        log.warning("get_webhook_info failed: %s", e)
        return None

def ensure_webhook_once():
    if not WEBHOOK_URL:
        log.info("WEBHOOK_URL не задан — пропускаем ensure_webhook_once().")
        return

    info = _get_webhook_info_safe()
    current_url = getattr(info, "url", "") if info is not None else ""
    if current_url == WEBHOOK_URL:
        log.info("Webhook уже установлен: %s", WEBHOOK_URL)
        return

    log.info("Удаляю старый webhook (если был)...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(0.3)
    except Exception as e:
        log.warning("delete_webhook: %s", e)

    log.info("Устанавливаю новый webhook → %s", WEBHOOK_URL)
    try:
        bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        log.info("set_webhook: ok")
    except Exception as e:
        log.exception("set_webhook failed: %s", e)
        raise

def ensure_webhook_once_safe():
    """Атомарная защита lockfile-ом от параллельных попыток в нескольких воркерах."""
    if not WEBHOOK_URL:
        return
    try:
        created = False
        try:
            with open(LOCKFILE, "x"):
                pass
            created = True
        except FileExistsError:
            created = False

        if not created:
            log.info("Lockfile существует — пропускаем установку вебхука в этом процессе.")
            return

        ensure_webhook_once()
    except Exception as e:
        log.exception("ensure_webhook_once_safe error: %s", e)
    # intentionally leave lockfile to avoid races (см. обсуждение). Убрать при необходимости.

def _startup_background_task(delay: float = 1.0):
    """
    Фон: делаем небольшую задержку и затем:
      - проверяем API (connectionChecker.check_all_apis)
      - пытаемся поставить webhook (если настроен)
    Это НЕ блокирует импорт и не вызывает ошибок при старте gunicorn.
    """
    time.sleep(delay)
    log.info("Фоновая стартовая задача: проверка API и (возможно) установка webhook...")
    # Проверяем API (Telegram/Gemini/DB) если функция доступна
    try:
        if hasattr(connectionChecker, "check_all_apis"):
            # check_all_apis обычно блокирует; выполняем её в фоне
            ok = connectionChecker.check_all_apis(bot)
            log.info("connectionChecker.check_all_apis returned: %s", ok)
        else:
            log.info("connectionChecker.check_all_apis отсутствует.")
    except Exception as e:
        log.exception("Ошибка при check_all_apis: %s", e)

    # Ставим webhook (если задано)
    try:
        ensure_webhook_once_safe()
    except Exception as e:
        log.exception("Ошибка при ensure_webhook_once_safe: %s", e)

# Запускаем демонический поток при импорте (не блокирует gunicorn)
_thread = Thread(target=_startup_background_task, args=(1.0,), daemon=True)
_thread.start()

# ----------------- Запуск (локально) -----------------
if __name__ == "__main__":
    # Для локальной отладки — можно запустить Flask, но на продакшне используем gunicorn main:app
    port = int(os.getenv("PORT", "8080"))
    log.info("Запуск dev сервера Flask (используйте gunicorn для продакшна): port=%s", port)
    app.run(host="0.0.0.0", port=port)