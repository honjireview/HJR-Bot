# -*- coding: utf-8 -*-
"""
main.py — безопасная установка webhook для Telegram + Flask

Вместо установки webhook при импорте, мы запускаем установку
в фоне при первом HTTP-запросе и используем простой lock-file,
чтобы минимизировать повторные попытки при работе в нескольких
процессах/воркерах.

Скопируйте этот файл в проект (замените при необходимости
переменные окружения в Railway) и разверните.
"""

import os
import time
import logging
from threading import Thread
from flask import Flask, request, abort
import telebot

# -------- ЛОГИ --------
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot")

# -------- ОКРУЖЕНИЕ --------
def env(name: str, fallback: str | None = None) -> str:
    val = os.getenv(name, fallback)
    if val is None or str(val).strip() == "":
        raise RuntimeError(f"Не найдено обязательное окружение: {name}")
    return str(val).strip()

# Поддерживаем и TELEGRAM_TOKEN, и BOT_TOKEN (возьмём что задано)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_TOKEN или BOT_TOKEN в окружении.")

# WEBHOOK_BASE_URL можно задавать как:
# - полную ссылку: https://hjr-bot-production.up.railway.app
# - или домен без схемы: hjr-bot-production.up.railway.app
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")
if not WEBHOOK_BASE_URL:
    # на всякий случай пробуем альтернативные имена, если вдруг настроены
    WEBHOOK_BASE_URL = os.getenv("PUBLIC_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")

if not WEBHOOK_BASE_URL or str(WEBHOOK_BASE_URL).strip().lower() in ("none", ""):
    raise RuntimeError(
        "Не найден WEBHOOK_BASE_URL в окружении. "
        "Укажи публичный домен Railway, например: https://hjr-bot-production.up.railway.app"
    )

WEBHOOK_BASE_URL = WEBHOOK_BASE_URL.strip().rstrip("/")
if not WEBHOOK_BASE_URL.startswith("http://") and not WEBHOOK_BASE_URL.startswith("https://"):
    WEBHOOK_BASE_URL = "https://" + WEBHOOK_BASE_URL

# Итоговый URL вебхука
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}/webhook/{TELEGRAM_TOKEN}"

# -------- TELEBOT + FLASK --------
# parse_mode можно настроить; у вас был HTML
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# ВАЖНО: lockfile чтобы минимизировать параллельные попытки установки webhook
LOCKFILE = "/tmp/hjr_set_webhook.lock"


# ----------------- handlers (оставьте свои хэндлеры внутри) -----------------
@bot.message_handler(commands=["start", "help"])
def on_start(message):
    bot.reply_to(message, "Бот на вебхуках запущен и готов 🔔")


@bot.message_handler(func=lambda _msg: True, content_types=["text"])
def echo(message):
    bot.send_message(message.chat.id, f"Эхо: {message.text}")


# ----------------- webhook route -----------------
@app.post(f"/webhook/{TELEGRAM_TOKEN}")
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        abort(400)
    update = telebot.types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return "ok", 200


# Health endpoints
@app.get("/")
def root():
    return "OK", 200


@app.get("/healthz")
def health():
    return "healthy", 200


# ----------------- ensure_webhook logic -----------------
def ensure_webhook_once():
    """Ставит webhook строго на указанный WEBHOOK_URL.
    Не должен вызываться при импорте (в этом файле мы запускаем
    его в before_first_request — см. ниже).
    """
    try:
        info = bot.get_webhook_info()
    except Exception as e:
        log.warning("get_webhook_info failed: %s", e)
        info = None

    current_url = getattr(info, "url", "") if info is not None else ""
    if current_url == WEBHOOK_URL:
        log.info("Webhook уже установлен: %s", WEBHOOK_URL)
        return

    # Удаляем старый webhook (на всякий случай) и ставим новый
    log.info("Удаляю старый webhook (если был)...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(0.5)
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
    """Простейшая защита от многократного выполнения в нескольких
    процессах/воркерах — создаём lock-file атомарно через mode='x'.
    """
    try:
        # пытаемся создать lockfile атомарно
        fd = None
        try:
            # open with 'x' — создаёт файл, если его нет, иначе бросает FileExistsError
            with open(LOCKFILE, 'x'):
                pass
        except FileExistsError:
            log.info("Lockfile существует, пропускаем установку вебхука в этом процессе")
            return

        # Если мы здесь — lockfile создан нами
        try:
            ensure_webhook_once()
        finally:
            # Оставляем lockfile как маркер — можно не удалять.
            # Если хотите удалять, расскомментируйте следующую строку.
            # try: os.remove(LOCKFILE)
            # except Exception: pass
            pass
    except Exception as e:
        log.exception("ensure_webhook_once_safe error: %s", e)


# ----------------- запуск установки в фоне при первом запросе -----------------
def _ensure_webhook_background():
    try:
        ensure_webhook_once_safe()
    except Exception as e:
        log.exception("ensure_webhook_once failed in background: %s", e)


@app.before_first_request
def schedule_webhook_setup():
    """
    Запускает установку webhook в фоне при первом HTTP-запросе.
    Это предотвращает блокировки при импорте и гарантирует, что
    webhook будет попытан установить ровно один раз в процессе.
    """
    t = Thread(target=_ensure_webhook_background, daemon=True)
    t.start()


# ----------------- запуск локально / gunicorn -----------------
if __name__ == '__main__':
    port = int(os.getenv("PORT", "8080"))
    # Для локальной отладки удобно запустить Flask напрямую
    app.run(host="0.0.0.0", port=port)

# Объект app нужен gunicorn'у: main:app
# При деплое в Railway Procfile обычно: web: gunicorn -w 1 -k gthread main:app