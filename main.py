# -*- coding: utf-8 -*-

import os
import time
import logging
import subprocess
from threading import Thread
from flask import Flask, request, abort
import telebot
from datetime import datetime

# --- ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ ДЛЯ ХЭША КОММИТА ---
COMMIT_HASH = "N/A"
try:
    # Проверяем, что мы находимся в git-репозитории
    subprocess.check_output(['git', 'rev-parse', '--is-inside-work-tree'], stderr=subprocess.STDOUT)
    COMMIT_HASH = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
    print(f"[INFO] Git-коммит успешно определен: {COMMIT_HASH}")
except (subprocess.CalledProcessError, FileNotFoundError):
    print(f"[WARN] Не удалось получить Git-коммит. Установлено значение по умолчанию: {COMMIT_HASH}")


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
                # Пропускаем, если данные по какой-то причине некорректны
                if not appeal_data or 'case_id' not in appeal_data:
                    continue

                case_id = appeal_data['case_id']

                # Логика досрочного завершения
                expected_responses = appeal_data.get('expected_responses')
                if expected_responses is not None:
                    council_answers = appeal_data.get('council_answers') or []
                    if len(council_answers) >= expected_responses:
                        log.info(f"Досрочное завершение для дела #{case_id}: получено {len(council_answers)}/{expected_responses} ответов.")
                        # ИСПРАВЛЕНО: Передаем уже полученные данные, а не ID
                        finalize_appeal(appeal_data, bot, COMMIT_HASH)
                        continue

                # Логика завершения по истечении 24 часов
                expires_at = appeal_data.get('timer_expires_at')
                if expires_at and datetime.now(expires_at.tzinfo) > expires_at:
                    log.info(f"Найден просроченный таймер для дела #{case_id}. Запускаю финальное рассмотрение.")
                    # ИСПРАВЛЕНО: Передаем уже полученные данные, а не ID
                    finalize_appeal(appeal_data, bot, COMMIT_HASH)

        except Exception as e:
            log.error(f"Критическая ошибка в фоновой задаче проверки таймеров: {e}")
        time.sleep(60)

background_thread = Thread(target=startup_and_timer_tasks, daemon=True)
background_thread.start()