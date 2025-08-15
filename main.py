# -*- coding: utf-8 -*-
import os
import sys
import time
from flask import Flask, request, abort
import telebot

# локальные модули проекта
import botHandlers
import connectionChecker

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в окружении.")

WEBHOOK_BASE = os.getenv("WEBHOOK_BASE_URL")  # например https://your-service.up.railway.app
if not WEBHOOK_BASE:
    raise RuntimeError("Не найден WEBHOOK_BASE_URL в окружении. Установите публичный URL вашего сервиса.")

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = WEBHOOK_BASE.rstrip("/") + WEBHOOK_PATH

# создаём бота
bot = telebot.TeleBot(BOT_TOKEN)

app = Flask(__name__)

def setup():
    # Удалим старый webhook если есть, проверим внешние API и зарегистрируем handlers
    try:
        print("[INFO] Удаляю старый webhook (если установлен)...")
        bot.remove_webhook()
        time.sleep(0.3)
    except Exception as e:
        print(f"[WARN] Ошибка при удалении webhook: {e}")

    try:
        ok = connectionChecker.check_all_apis(bot)
    except Exception as e:
        print(f"[FATAL] Ошибка в check_all_apis: {e}")
        ok = False

    if not ok:
        print("[FATAL] Не пройдены проверки API — завершаем.")
        sys.exit(1)

    try:
        print("[INFO] Регистрирую обработчики...")
        botHandlers.register_handlers(bot)
        print("[INFO] Обработчики зарегистрированы.")
    except Exception as e:
        print(f"[FATAL] Не удалось зарегистрировать обработчики: {e}")
        raise

    # Устанавливаем webhook на Telegram
    try:
        print(f"[INFO] Устанавливаю webhook: {WEBHOOK_URL}")
        bot.remove_webhook()
        time.sleep(0.2)
        res = bot.set_webhook(url=WEBHOOK_URL)
        if not res:
            print("[ERROR] Не удалось установить webhook (bot.set_webhook вернул False).")
            sys.exit(1)
        print("[OK] Webhook установлен.")
    except Exception as e:
        print(f"[FATAL] Ошибка при установке webhook: {e}")
        raise

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook_handler():
    # Telegram будет POSTить сюда обновления
    if request.method == "POST":
        try:
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
            return "", 200
        except Exception as e:
            print(f"[ERROR] Ошибка обработки webhook update: {e}")
            return "", 500
    else:
        abort(405)

@app.route("/", methods=["GET"])
def index():
    return "ok", 200

if __name__ == "__main__":
    setup()
    port = int(os.environ.get("PORT", 8080))
    # В Railway нужен запуск Flask через порт окружения
    print(f"[INFO] Запускаем Flask на 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)