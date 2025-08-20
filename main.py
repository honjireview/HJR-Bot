# -*- coding: utf-8 -*-

import os
import time
import logging
import subprocess
from threading import Thread
from flask import Flask, request, abort
import telebot
from datetime import datetime

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---

# ИСПРАВЛЕНО: Читаем системную переменную Railway для хеша коммита
# [:7] берет первые 7 символов, чтобы хеш был коротким и читаемым
COMMIT_HASH = os.getenv("RAILWAY_GIT_COMMIT_SHA", "N/A")[:7]
print(f"[INFO] Версия коммита определена как: {COMMIT_HASH}")

# ИСПРАВЛЕНО: Читаем переменную для версии релиза, которую вы создадите в Railway
# Если переменной нет, будет указано, что это dev-версия
BOT_VERSION = os.getenv("BOT_RELEASE_VERSION", "dev-build")
print(f"[INFO] Версия релиза определена как: {BOT_VERSION}")


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
from handlers import register_all_handlers

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
    from geminiProcessor import finalize_appeal
    from handlers.admin_flow import sync_editors_list

    log.info("Запуск фоновых задач...")
    time.sleep(3)

    if not connectionChecker.check_all_apis(bot):
        log.error("Проверка API провалилась. Бот может работать некорректно.")
        return

    log.info("Запуск первоначальной синхронизации списка редакторов...")
    sync_editors_list(bot)

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

    log.info("Запущена фоновая задача проверки таймеров.")
    while True:
        try:
            appeals_in_collection = appealManager.get_appeals_in_collection()
            for appeal_data in appeals_in_collection:
                if not appeal_data or 'case_id' not in appeal_data:
                    continue

                case_id = appeal_data['case_id']

                expected_responses = appeal_data.get('expected_responses')
                if expected_responses is not None:
                    council_answers = appeal_data.get('council_answers') or []
                    if len(council_answers) >= expected_responses:
                        log.info(f"Досрочное завершение для дела #{case_id}: получено {len(council_answers)}/{expected_responses} ответов.")
                        # ИСПРАВЛЕНО: Передаем обе переменные: коммит и версию релиза
                        finalize_appeal(appeal_data, bot, COMMIT_HASH, BOT_VERSION)
                        continue

                expires_at = appeal_data.get('timer_expires_at')
                if expires_at and datetime.now(expires_at.tzinfo) > expires_at:
                    log.info(f"Найден просроченный таймер для дела #{case_id}. Запускаю финальное рассмотрение.")
                    # ИСПРАВЛЕНО: Передаем обе переменные: коммит и версию релиза
                    finalize_appeal(appeal_data, bot, COMMIT_HASH, BOT_VERSION)

        except Exception as e:
            log.error(f"Критическая ошибка в фоновой задаче проверки таймеров: {e}")
        time.sleep(60)

background_thread = Thread(target=startup_and_timer_tasks, daemon=True)
background_thread.start()