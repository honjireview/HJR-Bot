# -*- coding: utf-8 -*-
import os
import sys
import time
import telebot
from telebot import apihelper

# локальные модули
import botHandlers
import connectionChecker

# --- Конфигурация через ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в окружении. Убедитесь, что переменная установлена.")

WEBHOOK_BASE = os.getenv("WEBHOOK_BASE_URL")  # обязателен: https://your-app.up.railway.app (без / на конце)
if not WEBHOOK_BASE:
    raise RuntimeError("Не найден WEBHOOK_BASE_URL в окружении. Установите публичный URL вашего сервиса (например https://myapp.up.railway.app)")

# Путь webhook включает токен, чтобы URL был секретным
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = WEBHOOK_BASE.rstrip("/") + WEBHOOK_PATH

# Flask/Telebot
from flask import Flask, request, abort

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

def setup_and_set_webhook():
    """Проверка API, регистрация обработчиков и установка webhook (с ретраями)."""
    # 1) Проверяем внешние API (Telegram, Gemini, Postgres)
    try:
        ok = connectionChecker.check_all_apis(bot)
    except Exception as e:
        print(f"[FATAL] Ошибка в check_all_apis: {e}")
        ok = False

    if not ok:
        print("[FATAL] Не пройдены проверки API — процесс завершается.")
        sys.exit(1)

    # 2) Регистрируем обработчики
    try:
        print("[INFO] Регистрирую обработчики...")
        botHandlers.register_handlers(bot)
        print("[INFO] Обработчики зарегистрированы.")
    except Exception as e:
        print(f"[FATAL] Не удалось зарегистрировать обработчики: {e}")
        raise

    # 3) Удаляем старые webhook'и и устанавливаем новый (с ретраями)
    try:
        print("[INFO] Удаляю старый webhook (если есть)...")
        bot.remove_webhook()
        time.sleep(0.2)
    except Exception as e:
        print(f"[WARN] Ошибка при удалении старого webhook: {e}")

    max_attempts = 5
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[INFO] Попытка установить webhook (attempt {attempt}/{max_attempts}) → {WEBHOOK_URL}")
            result = bot.set_webhook(url=WEBHOOK_URL)
            # telebot обычно возвращает True/False; обработаем оба случая
            if result is True or (hasattr(result, "ok") and getattr(result, "ok", False)):
                print("[OK] Webhook успешно установлен.")
                return
            else:
                print(f"[ERROR] bot.set_webhook вернул неуспех: {result}")
        except Exception as e:
            print(f"[ERROR] Exception при set_webhook (attempt {attempt}): {e}")
        # экспоненциальная пауза перед следующим повтором
        time.sleep(delay)
        delay *= 2

    print("[FATAL] Не удалось установить webhook после нескольких попыток. Завершаю процесс (exit 1).")
    sys.exit(1)

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook_handler():
    """Обработчик входящих обновлений от Telegram (POST)."""
    if request.method == "POST":
        try:
            json_str = request.get_data().decode("utf-8")
            update = telebot.types.Update.de_json(json_str)
            bot.process_new_updates([update])
            return "", 200
        except Exception as e:
            # В логах увидим подробности
            print(f"[ERROR] Ошибка обработки webhook update: {e}")
            return "", 500
    else:
        abort(405)

@app.route("/", methods=["GET"])
def index():
    return "ok", 200

if __name__ == "__main__":
    # Полный setup: проверка API, регистрация обработчиков, установка webhook
    setup_and_set_webhook()
    port = int(os.environ.get("PORT", 8080))
    print(f"[INFO] Flask app запущен (webhook mode) на 0.0.0.0:{port}")
    # Gunicorn предпочтительнее в продакшене; но app.run в контейнере тоже работает.
    app.run(host="0.0.0.0", port=port)