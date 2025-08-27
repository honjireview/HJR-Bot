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
COMMIT_HASH = os.getenv("RAILWAY_GIT_COMMIT_SHA", "N/A")[:7]
print(f"[INFO] Версия коммита определена как: {COMMIT_HASH}")
BOT_VERSION = os.getenv("BOT_RELEASE_VERSION", "dev-build")
print(f"[INFO] Версия релиза определена как: {BOT_VERSION}")

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot")

# --- Переменные окружения ---
HJRBOT_TELEGRAM_TOKEN = os.getenv("HJRBOT_TELEGRAM_TOKEN")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")
COUNCIL_CHAT_ID = os.getenv("EDITORS_GROUP_ID") # Используем для stop_poll

if not HJRBOT_TELEGRAM_TOKEN:
    raise RuntimeError("Не найден HJRBOT_TELEGRAM_TOKEN в окружении.")

# --- Создание экземпляров ---
bot = telebot.TeleBot(HJRBOT_TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Импорт модулей ---
from app.core import connection as connectionChecker
from app.core import appeal_manager as appealManager
from app.handlers import register_all_handlers
from app.utils.council_helpers import resolve_council_id

# --- Регистрация обработчиков ---
register_all_handlers(bot)

# --- Webhook route и Health Check ---
@app.post(f"/webhook/{HJRBOT_TELEGRAM_TOKEN}")
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data(as_text=True))
        bot.process_new_updates([update])
        return "ok", 200
    abort(400)

@app.get("/")
def health_check():
    return "Bot is running.", 200

def startup_and_timer_tasks():
    from app.core.gemini import finalize_appeal, finalize_review
    from app.handlers.admin import sync_editors_list

    log.info("Запуск фоновых задач...")
    time.sleep(3)

    if not connectionChecker.check_all_apis(bot):
        log.error("Проверка API провалилась. Бот может работать некорректно.")
        return

    log.info("Запуск первоначальной синхронизации списка редакторов...")
    sync_editors_list(bot)

    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL.strip('/')}/webhook/{HJRBOT_TELEGRAM_TOKEN}"
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
            active_appeals = appealManager.get_appeals_in_collection()
            for appeal_data in active_appeals:
                if not appeal_data or 'case_id' not in appeal_data:
                    continue

                case_id = appeal_data['case_id']
                status = appeal_data.get('status')
                expires_at = appeal_data.get('timer_expires_at')

                # Проверяем, истек ли таймер
                if not (expires_at and datetime.now(expires_at.tzinfo) > expires_at):
                    # Если таймер не истек, проверяем на досрочное завершение для обычных апелляций
                    if status == 'collecting':
                        expected_responses = appeal_data.get('expected_responses')
                        if expected_responses is not None and expected_responses > 0:
                            council_answers = appeal_data.get('council_answers') or []
                            if len(council_answers) >= expected_responses:
                                log.info(f"Досрочное завершение для дела #{case_id}")
                                finalize_appeal(appeal_data, bot, COMMIT_HASH, BOT_VERSION)
                    continue # Переходим к следующему делу, если таймер не истек

                # Если таймер истек, обрабатываем в зависимости от статуса
                if status == 'collecting':
                    log.info(f"Просроченный таймер для дела #{case_id}.")
                    finalize_appeal(appeal_data, bot, COMMIT_HASH, BOT_VERSION)

                elif status == 'review_poll_pending':
                    log.info(f"Таймер голосования по пересмотру дела #{case_id} истек. Проверяю результаты.")
                    review_data = appeal_data.get('review_data', {})
                    poll_message_id = review_data.get('poll_message_id')

                    if poll_message_id and COUNCIL_CHAT_ID:
                        final_poll = bot.stop_poll(COUNCIL_CHAT_ID, poll_message_id)

                        total_members = bot.get_chat_member_count(COUNCIL_CHAT_ID) - 1 # Вычитаем самого бота
                        inactive_members = appealManager.count_inactive_editors()
                        active_members = total_members - inactive_members
                        threshold = active_members / 2

                        for_votes = 0
                        for opt in final_poll.options:
                            if "да" in opt.text.lower():
                                for_votes = opt.voter_count

                        if for_votes > threshold:
                            log.info(f"Пересмотр дела #{case_id} одобрен ({for_votes} > {threshold}).")
                            appealManager.update_appeal(case_id, "status", "reviewing")
                            new_expires_at = datetime.utcnow() + timedelta(hours=24)
                            appealManager.update_appeal(case_id, "timer_expires_at", new_expires_at)
                            bot.send_message(COUNCIL_CHAT_ID, f"📣 Пересмотр дела №{case_id} одобрен Советом. Начался 24-часовой сбор дополнительных аргументов через команду `/replyrecase {case_id}` в ЛС.", message_thread_id=appeal_data.get("message_thread_id"))
                        else:
                            log.info(f"Пересмотр дела #{case_id} отклонен ({for_votes} <= {threshold}).")
                            appealManager.update_appeal(case_id, "status", "closed") # Возвращаем статус
                            bot.send_message(COUNCIL_CHAT_ID, f"Пересмотр дела №{case_id} не набрал абсолютного большинства голосов и был отклонен.", message_thread_id=appeal_data.get("message_thread_id"))

                elif status == 'reviewing':
                    log.info(f"Просроченный таймер для ПЕРЕСМОТРА дела #{case_id}.")
                    finalize_review(appeal_data, bot, COMMIT_HASH, BOT_VERSION)

        except Exception as e:
            log.error(f"Критическая ошибка в фоновой задаче: {e}", exc_info=True)
        time.sleep(60)

background_thread = Thread(target=startup_and_timer_tasks, daemon=True)
background_thread.start()