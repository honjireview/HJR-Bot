import os
import logging
from flask import Flask, request
import telebot

# --- ЛОГИ ---
logging.basicConfig(level=logging.INFO)

# --- Конфиги ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # hjr-bot-production.up.railway.app
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"https://{WEBHOOK_HOST}{WEBHOOK_PATH}"

# --- Инициализация бота ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Хэндлеры бота ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(message.chat.id, "✅ Бот запущен через webhook + gunicorn!")

# --- Flask endpoint для Telegram ---
@app.route(WEBHOOK_PATH, methods=['POST'])
def webhook():
    try:
        update = request.get_data().decode("utf-8")
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    except Exception as e:
        logging.exception(e)
    return "OK", 200

# --- Flask healthcheck (Railway ping) ---
@app.route("/", methods=['GET'])
def index():
    return "Бот работает через webhook + gunicorn", 200

# --- Настройка вебхука при старте ---
with app.app_context():
    logging.info("Удаляю старый webhook...")
    bot.remove_webhook()
    logging.info(f"Устанавливаю новый webhook → {WEBHOOK_URL}")
    bot.set_webhook(url=WEBHOOK_URL)
    logging.info("Webhook установлен!")

# --- Запуск через gunicorn ---
# !!! НЕ ПИШЕМ app.run() !!!
# Gunicorn возьмет app сам