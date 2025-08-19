# -*- coding: utf-8 -*-

import os
import time
import logging
from threading import Thread
from flask import Flask, request, abort
import telebot

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot")

# --- Переменные окружения ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_TOKEN в окружении.")

# --- Создание экземпляров ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Импорт модулей ---
import connectionChecker
import appealManager
from handlers import register_all_handlers # Этот импорт теперь будет работать

# --- Регистрация обработчиков ---
register_all_handlers(bot)

# --- Webhook route и Health Check ---
@app.post(f"/webhook/{TELEGRAM_TOKEN}")
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data(as_text=True))
        bot.process_new_updates([update])
        return "ok", 200
    abort(400)

@app.get("/")
def health_check():
    return "Bot is running.", 200

# --- Фоновые задачи ---
def startup_and_timer_tasks():
    # ВАЖНО: Импортируем finalize_appeal здесь, а не в начале файла
    from handlers.council_flow import finalize_appeal

    log.info("Запуск фоновых задач...")
    time.sleep(3) # Даем gunicorn запуститься

    # 1. Проверка API
    if not connectionChecker.check_all_apis(bot):
        log.error("Проверка API провалилась. Бот может работать некорректно.")
        return

    # 2. Установка Webhook
    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL.strip('/')}/webhook/{TELEGRAM_TOKEN}"
        current_webhook = bot.get_webhook_info()
        if current_webhook.url != webhook_url:
            log.info(f"Установка webhook на: {webhook_url}")
            bot.remove_webhook()
            time.sleep(0.5)
            bot.set_webhook(url=webhook_url)
            log.info("Webhook успешно установлен.")
        else:
            log.info("Webhook уже установлен.")
    else:
        log.warning("WEBHOOK_BASE_URL не задан. Webhook не будет установлен.")

    # 3. Бесконечный цикл проверки таймеров
    log.info("Запущена фоновая задача проверки таймеров.")
    while True:
        try:
            expired_appeals = appealManager.get_expired_appeals()
            for appeal in expired_appeals:
                case_id = appeal['case_id']
                log.info(f"Найден просроченный таймер для дела #{case_id}. Запускаю финальное рассмотрение.")
                finalize_appeal(case_id, bot)
        except Exception as e:
            log.error(f"Ошибка в фоновой задаче проверки таймеров: {e}")

        time.sleep(60)

# Запускаем фоновые задачи при старте
background_thread = Thread(target=startup_and_timer_tasks, daemon=True)
background_thread.start()