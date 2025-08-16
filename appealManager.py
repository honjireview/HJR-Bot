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
# Railway предоставляет их автоматически
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_TOKEN в окружении.")

# --- Создание экземпляров ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Импорт модулей после создания bot ---
# Это гарантирует, что у них будет доступ к нашему экземпляру bot
import connectionChecker
import botHandlers
import appealManager

# --- Регистрация обработчиков ---
botHandlers.register_handlers(bot)

# --- Webhook route для Telegram ---
@app.post(f"/webhook/{TELEGRAM_TOKEN}")
def telegram_webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
        bot.process_new_updates([update])
        return "ok", 200
    abort(400)

# --- Health check для Railway ---
@app.get("/")
def health_check():
    return "Bot is running.", 200

# --- Фоновая задача для проверки таймеров ---
def check_expired_appeals_periodically():
    """
    Бесконечный цикл, который раз в 60 секунд проверяет БД на просроченные апелляции.
    """
    while True:
        try:
            # Получаем все дела, у которых истек таймер и статус еще не 'closed'
            appeals_to_finalize = appealManager.get_expired_appeals()
            for appeal in appeals_to_finalize:
                case_id = appeal['case_id']
                print(f"Найден просроченный таймер для дела #{case_id}. Запускаю финальное рассмотрение.")
                # Вызываем финальную функцию из botHandlers
                botHandlers.finalize_appeal(case_id, bot)
        except Exception as e:
            log.error(f"Ошибка в фоновой задаче проверки таймеров: {e}")

        # Пауза на 60 секунд перед следующей проверкой
        time.sleep(60)

# --- Запуск ---
if __name__ == "__main__":
    log.info("Проверка API и подключений...")
    if connectionChecker.check_all_apis(bot):
        log.info("Все проверки пройдены.")

        # Установка Webhook
        if WEBHOOK_BASE_URL:
            webhook_url = f"{WEBHOOK_BASE_URL.strip('/')}/webhook/{TELEGRAM_TOKEN}"
            log.info(f"Установка webhook на: {webhook_url}")
            bot.remove_webhook()
            time.sleep(0.5)
            bot.set_webhook(url=webhook_url)
            log.info("Webhook успешно установлен.")
        else:
            log.warning("WEBHOOK_BASE_URL не задан. Webhook не будет установлен.")

        # Запуск фоновой задачи для таймеров в отдельном потоке
        timer_thread = Thread(target=check_expired_appeals_periodically, daemon=True)
        timer_thread.start()
        log.info("Фоновая задача для проверки таймеров запущена.")

        # Этот код больше не нужен, так как Railway использует Procfile
        # port = int(os.getenv("PORT", "8080"))
        # app.run(host="0.0.0.0", port=port)
    else:
        log.error("Бот не может быть запущен из-за ошибок API.")