# app/main.py
# -*- coding: utf-8 -*-
import os
import time
import logging
from threading import Thread
from flask import Flask, request, abort
import telebot

from app.core.config import BOT_TOKEN, WEBHOOK_BASE_URL
from app.core.bot import bot
from app.core.db import check_all_connections
from app.handlers import register_all_handlers
from app.services import timer_service, editor_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot.main")

app = Flask(__name__)
register_all_handlers(bot)

@app.post(f"/webhook/{BOT_TOKEN}")
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data(as_text=True))
        bot.process_new_updates([update])
        return "ok", 200
    abort(403)

@app.get("/")
def health_check():
    return "Bot is running.", 200

def startup_and_background_tasks():
    log.info("Ожидание 3 секунды для инициализации...")
    time.sleep(3)

    if not check_all_connections(bot):
        log.critical("Проверка соединений провалилась. Бот не может стартовать.")
        return

    log.info("Первоначальная синхронизация списка редакторов...")
    editor_service.sync_editors_list(bot)

    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL.strip('/')}/webhook/{BOT_TOKEN}"
        current_webhook = bot.get_webhook_info()
        if current_webhook.url != webhook_url:
            log.info(f"Установка webhook: {webhook_url}")
            bot.remove_webhook()
            time.sleep(0.5)
            bot.set_webhook(url=webhook_url)
        else:
            log.info("Webhook уже установлен.")
    else:
        log.warning("WEBHOOK_BASE_URL не задан. Запуск в режиме polling.")
        # Для локального запуска без вебхука
        bot.remove_webhook()
        Thread(target=bot.polling, args=({'none_stop': True}), daemon=True).start()

    timer_service.start_timer_check(bot)


background_thread = Thread(target=startup_and_background_tasks, daemon=True)
background_thread.start()