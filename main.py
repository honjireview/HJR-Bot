# -*- coding: utf-8 -*-

import telebot
import os
from connectionChecker import check_all_apis
import botHandlers # <-- Импортируем наш новый файл с обработчиками

# --- ОСНОВНОЙ ФАЙЛ ДЛЯ ЗАПУСКА БОТА ---

if __name__ == '__main__':
    # 1. Получаем токен напрямую из переменных окружения
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        raise ValueError("Не найден BOT_TOKEN. Убедитесь, что переменная окружения установлена.")

    # 2. Создаем экземпляр бота
    bot = telebot.TeleBot(BOT_TOKEN)

    # 3. Проверяем доступность всех API
    if check_all_apis(bot):
        # 4. Регистрируем все обработчики сообщений из файла botHandlers.py
        botHandlers.register_handlers(bot)

        print("\nОсновной бот запущен и готов к работе.")

        # 5. Запускаем бота
        bot.polling(non_stop=True)
    else:
        print("\nБот не может быть запущен из-за ошибок API.")