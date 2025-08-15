import os
import time
import logging
from flask import Flask, request, abort
import telebot

# -------- ЛОГИ --------
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("hjr-bot")

# -------- ОКРУЖЕНИЕ --------
def env(name: str, fallback: str | None = None) -> str:
    val = os.getenv(name, fallback)
    if val is None or str(val).strip() == "":
        raise RuntimeError(f"Не найдено обязательное окружение: {name}")
    return str(val).strip()

# Поддерживаем и TELEGRAM_TOKEN, и BOT_TOKEN (возьмём что задано)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не найден TELEGRAM_TOKEN или BOT_TOKEN в окружении.")

# WEBHOOK_BASE_URL можно задавать как:
# - полную ссылку: https://hjr-bot-production.up.railway.app
# - или домен без схемы: hjr-bot-production.up.railway.app
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL")
if not WEBHOOK_BASE_URL:
    # на всякий случай пробуем альтернативные имена, если вдруг настроены
    WEBHOOK_BASE_URL = os.getenv("PUBLIC_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")

if not WEBHOOK_BASE_URL or str(WEBHOOK_BASE_URL).strip().lower() in ("none", ""):
    raise RuntimeError(
        "Не найден WEBHOOK_BASE_URL в окружении. "
        "Укажи публичный домен Railway, например: https://hjr-bot-production.up.railway.app"
    )

WEBHOOK_BASE_URL = WEBHOOK_BASE_URL.strip().rstrip("/")
if not WEBHOOK_BASE_URL.startswith("http://") and not WEBHOOK_BASE_URL.startswith("https://"):
    WEBHOOK_BASE_URL = "https://" + WEBHOOK_BASE_URL

# Итоговый URL вебхука
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}/webhook/{TELEGRAM_TOKEN}"

# -------- TELEBOT + FLASK --------
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# Простейшие хэндлеры — оставь свои внутри
@bot.message_handler(commands=["start", "help"])
def on_start(message):
    bot.reply_to(message, "Бот на вебхуках запущен и готов 🔔")

@bot.message_handler(func=lambda _msg: True, content_types=["text"])
def echo(message):
    bot.send_message(message.chat.id, f"Эхо: {message.text}")

# Вебхук-роут. Telegram будет бить сюда.
@app.post(f"/webhook/{TELEGRAM_TOKEN}")
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        abort(400)
    update = telebot.types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return "ok", 200

# Хелсчеки
@app.get("/")
def root():
    return "OK", 200

@app.get("/healthz")
def health():
    return "healthy", 200

def ensure_webhook_once():
    """
    Ставит вебхук только при необходимости.
    Без спама и с удалением старого URL, если он другой.
    """
    info = bot.get_webhook_info()
    if info and getattr(info, "url", "") == WEBHOOK_URL:
        log.info("Webhook уже установлен: %s", WEBHOOK_URL)
        return

    log.info("Удаляю старый webhook...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(0.5)
    except Exception as e:
        log.warning("delete_webhook: %s", e)

    log.info("Устанавливаю новый webhook → %s", WEBHOOK_URL)
    # drop_pending_updates=True чтобы не тянуть старую очередь polling
    bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)

# ВАЖНО: ставим вебхук при импорте один раз.
# В Procfile ниже выставлено -w 1, так что запрос будет ровно один.
ensure_webhook_once()

# Объект app нужен gunicorn'у: main:app
# Запуск локально (если надо): python main.py
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)