# app/main.py
# -*- coding: utf-8 -*-
import logging
import time
from threading import Thread
from flask import Flask, request, abort
import telebot

# --- 1. Настройка и импорты (ИСПРАВЛЕНО НА ОТНОСИТЕЛЬНЫЕ) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("hjr-bot.main")

from .core.config import BOT_TOKEN, WEBHOOK_BASE_URL, WEBHOOK_PATH, WEBHOOK_SECRET
from .core.bot import bot
from .core.db import check_all_connections
from .handlers import register_all_handlers
from .services import timer_service, editor_service

# --- 2. Инициализация Flask ---
app = Flask(__name__)

# --- 3. Маршрут для вебхука ---
@app.post(WEBHOOK_PATH)
def process_webhook():
    log.info("Получен входящий запрос на вебхук...")
    try:
        if WEBHOOK_SECRET:
            secret_token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret_token != WEBHOOK_SECRET:
                log.warning(f"Отклонен запрос с неверным Secret Token.")
                abort(403)
            log.info("Secret Token успешно верифицирован.")

        if request.headers.get("content-type") == "application/json":
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
            log.info("Запрос успешно обработан.")
            return '', 200
        else:
            log.error(f"Отклонен запрос с неверным Content-Type: {request.headers.get('content-type')}")
            abort(403)

    except Exception as e:
        log.error(f"Критическая ошибка при обработке вебхука: {e}", exc_info=True)
        return "Webhook processing error", 500

# --- 4. Маршрут для проверки состояния ---
@app.get("/")
def health_check():
    return "HJR-Bot is running.", 200

# --- 5. Логика запуска ---
def startup_tasks():
    log.info("Ожидание 3 секунды для инициализации...")
    time.sleep(3)

    if not check_all_connections(bot):
        log.critical("Проверка соединений провалилась. Запуск отменен.")
        return

    register_all_handlers(bot)
    log.info("Все обработчики команд успешно зарегистрированы.")

    webhook_url = f"{WEBHOOK_BASE_URL.strip('/')}{WEBHOOK_PATH}"
    current_webhook = bot.get_webhook_info()

    if current_webhook.url != webhook_url or (WEBHOOK_SECRET and not current_webhook.has_custom_certificate):
        log.info(f"Требуется обновление вебхука. Устанавливаю на: {webhook_url}")
        bot.remove_webhook()
        time.sleep(0.5)
        success = bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET)
        if success:
            log.info("Вебхук успешно установлен.")
        else:
            log.error("Не удалось установить вебхук!")
    else:
        log.info(f"Вебхук уже корректно установлен на: {current_webhook.url}")

    log.info("Запуск первоначальной синхронизации редакторов...")
    editor_service.sync_editors_list(bot)
    timer_service.start_timer_check(bot)

startup_thread = Thread(target=startup_tasks, daemon=True)
startup_thread.start()