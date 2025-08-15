# -*- coding: utf-8 -*-
"""
main.py — безопасная установка webhook для Telegram + Flask

Работает стабильно под gunicorn: не блокирует импорт/инициализацию воркера,
не вызывает set_webhook синхронно при импорте. Установка webhook выполняется
в отдельном demon-потоке через короткую задержку.
"""
import os
import time
import logging
from threading import Thread
from typing import Optional

from flask import Flask, request, abort
import telebot

# -------- ЛОГИ --------
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot")

# -------- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ --------
# TELEGRAM_TOKEN обязателен — без него бот не будет работать
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_TOKEN или BOT_TOKEN в окружении.")

# WEBHOOK_BASE_URL — делаем опциональным: если его нет, мы не пытаемся ставить webhook.
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL") or os.getenv("PUBLIC_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")
if WEBHOOK_BASE_URL:
    WEBHOOK_BASE_URL = WEBHOOK_BASE_URL.strip().rstrip("/")
    if not WEBHOOK_BASE_URL.startswith("http://") and not WEBHOOK_BASE_URL.startswith("https://"):
        WEBHOOK_BASE_URL = "https://" + WEBHOOK_BASE_URL
    WEBHOOK_URL = f"{WEBHOOK_BASE_URL}/webhook/{TELEGRAM_TOKEN}"
else:
    WEBHOOK_URL = None
    log.warning("WEBHOOK_BASE_URL не найден; webhook не будет установлен автоматически.")

# -------- TELEBOT + FLASK --------
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# Lockfile для минимизации повторных установок в нескольких процессах
LOCKFILE = "/tmp/hjr_set_webhook.lock"


# ----------------- handlers (пример) -----------------
@bot.message_handler(commands=["start", "help"])
def on_start(message):
    bot.reply_to(message, "Бот на вебхуках запущен и готов 🔔")


@bot.message_handler(func=lambda _msg: True, content_types=["text"])
def echo(message):
    bot.send_message(message.chat.id, f"Эхо: {message.text}")


# ----------------- webhook route -----------------
@app.post(f"/webhook/{TELEGRAM_TOKEN}")
def telegram_webhook():
    # Telegram посылает application/json
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
def _get_current_webhook_info() -> Optional[object]:
    try:
        return bot.get_webhook_info()
    except Exception as e:
        log.warning("get_webhook_info failed: %s", e)
        return None


def ensure_webhook_once():
    """
    Устанавливает webhook на WEBHOOK_URL (если он задан).
    Вызывать только из фонового потока или при явном запуске.
    """
    if not WEBHOOK_URL:
        log.info("WEBHOOK_URL не задан — пропускаем установку вебхука.")
        return

    info = _get_current_webhook_info()
    current_url = getattr(info, "url", "") if info is not None else ""

    if current_url == WEBHOOK_URL:
        log.info("Webhook уже установлен: %s", WEBHOOK_URL)
        return

    log.info("Удаляю старый webhook (если был)...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(0.3)
    except Exception as e:
        log.warning("delete_webhook error (игнорируем): %s", e)

    log.info("Устанавливаю новый webhook → %s", WEBHOOK_URL)
    try:
        # устанавливаем webhook (синхронно, но в фоне, поэтому не блокирует импорт)
        bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        log.info("set_webhook: ok")
    except Exception as e:
        log.exception("set_webhook failed: %s", e)
        raise


def ensure_webhook_once_safe():
    """
    Защита от параллельных запусков: atomic create lockfile (mode='x').
    Если lockfile уже существует — предполагаем, что кто-то другой уже выполняет/выполнил установку.
    """
    if not WEBHOOK_URL:
        return

    try:
        # попытка атомарно создать lockfile
        try:
            with open(LOCKFILE, "x"):
                pass
            created = True
        except FileExistsError:
            created = False

        if not created:
            log.info("Lockfile обнаружен; пропускаем установку вебхука в этом процессе.")
            return

        # выполняем установку
        ensure_webhook_once()
    except Exception as e:
        log.exception("ensure_webhook_once_safe error: %s", e)
    # intentionally do not remove lockfile to avoid race on repeated restarts;
    # если хотите удалять — раскомментируйте следующий блок:
    # try:
    #     os.remove(LOCKFILE)
    # except Exception:
    #     pass


def _delayed_startup_hook(delay_seconds: float = 1.0):
    """
    Фоновая задача: ждёт короткую задержку и затем пытается поставить webhook.
    Запускать как daemon thread при импорте (не блокирует).
    """
    try:
        time.sleep(delay_seconds)
        log.info("Фоновая задача: попытка установки webhook (если нужно)...")
        ensure_webhook_once_safe()
    except Exception as e:
        log.exception("Ошибка фоновой задачи установки webhook: %s", e)


# Запускаем фоновый демонический поток при импорте — очень короткая задержка, чтобы избежать гонки старта
t = Thread(target=_delayed_startup_hook, args=(1.0,), daemon=True)
t.start()


# ----------------- запуск локально / gunicorn -----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)