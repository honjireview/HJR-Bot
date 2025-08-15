# -*- coding: utf-8 -*-

import telebot
import config
from connectionChecker import check_all_apis
import botHandlers # <-- Импортируем наш новый файл с обработчиками

# --- ОСНОВНОЙ ФАЙЛ ДЛЯ ЗАПУСКА БОТА ---

if __name__ == '__main__':
    # 1. Создаем экземпляр бота
    bot = telebot.TeleBot(config.BOT_TOKEN)

    # 2. Проверяем доступность всех API
    if check_all_apis(bot):
        # 3. Регистрируем все обработчики сообщений из файла botHandlers.py
        botHandlers.register_handlers(bot)

        print("\nОсновной бот запущен и готов к работе.")

        # 4. Запускаем бота
        bot.polling(non_stop=True)
    else:
        print("\nБот не может быть запущен из-за ошибок API.")