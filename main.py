# -*- coding: utf-8 -*-
import os
import time
import sys
import telebot
from telebot import apihelper

# Импортируем модули проекта (оставьте названия как в вашем проекте)
import botHandlers
import connectionChecker

# Получаем токен бота из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в окружении. Убедитесь, что переменная установлена.")

# Создаём бота
bot = telebot.TeleBot(BOT_TOKEN)

def safe_remove_webhook():
    """Пытаемся удалить webhook — если он есть, это освобождает возможность polling."""
    try:
        print("[INFO] Удаляю webhook (если он установлен)...")
        bot.remove_webhook()
        # даём Telegram немного времени, чтобы состояние обновилось
        time.sleep(0.5)
        print("[INFO] webhook удалён (или был отсутствующим).")
    except Exception as e:
        print(f"[WARN] Ошибка при удалении webhook: {e} — продолжаем запуск.")

def start_polling_with_retry():
    """
    Запускает polling. При возникновении 409 (conflict — другой getUpdates/webhook)
    пробует удалить webhook и запустить polling ещё раз.
    """
    try:
        print("[INFO] Запускаю polling...")
        bot.polling(non_stop=True)
    except apihelper.ApiTelegramException as e:
        code = getattr(e, "error_code", None)
        if code == 409 or "Conflict" in str(e):
            print("[ERROR] 409 Conflict: другой getUpdates/webhook активен. Попытка удалить webhook и перезапустить...")
            try:
                bot.remove_webhook()
                time.sleep(0.8)
                print("[INFO] Повторный запуск polling после удаления webhook...")
                bot.polling(non_stop=True)
            except Exception as e2:
                print(f"[FATAL] Polling не стартует после удаления webhook: {e2}")
                raise
        else:
            print(f"[ERROR] ApiTelegramException при polling: {e}")
            raise
    except Exception as e:
        print(f"[ERROR] Неожиданная ошибка polling: {e}")
        raise

if __name__ == "__main__":
    # 1) Сначала удалим webhook на всякий случай
    safe_remove_webhook()

    # 2) Проверяем все внешние API (Telegram, Gemini, PostgreSQL)
    #    connectionChecker.check_all_apis(bot) логирует детали
    try:
        ok = connectionChecker.check_all_apis(bot)
    except Exception as e:
        print(f"[FATAL] Ошибка в check_all_apis: {e}")
        ok = False

    if not ok:
        print("\nБот не может быть запущен из-за ошибок API (смотрите логи выше).")
        # При ошибке — завершаем процесс с ненулевым кодом, чтобы платформа могла пере деплоить/показать проблему
        sys.exit(1)

    # 3) Регистрируем обработчики (внутри botHandlers.register_handlers используется тот же объект bot)
    try:
        print("[INFO] Регистрирую обработчики...")
        botHandlers.register_handlers(bot)
        print("[INFO] Обработчики зарегистрированы.")
    except Exception as e:
        print(f"[FATAL] Не удалось зарегистрировать обработчики: {e}")
        raise

    print("\nОсновной бот запущен и готов к работе.")
    # 4) Запуск polling с защитой от 409
    try:
        start_polling_with_retry()
    except KeyboardInterrupt:
        print("[INFO] Остановка по сигналу KeyboardInterrupt.")
    except Exception as e:
        print(f"[FATAL] Bot stopped due to exception: {e}")
        # не скрываем ошибку — выводим в логи и завершаем
        raise