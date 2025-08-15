# -*- coding: utf-8 -*-

import telebot
import config  # Импортируем наш файл с токеном
from connectionChecker import check_all_apis

# --- СКРИПТ ДЛЯ ПОЛУЧЕНИЯ ID ЧАТА ---

bot = telebot.TeleBot(config.BOT_TOKEN)

# --- Безопасный способ для КАНАЛОВ ---
# Этот обработчик ловит событие, когда статус бота меняется
# (например, когда вы добавляете его в канал как администратора).
@bot.my_chat_member_handler()
def handle_chat_member_update(update):
    """
    Отлавливает добавление бота в чат/канал и выводит ID в консоль.
    """
    chat = update.chat
    print("--- Событие в чате ---")
    print(f"Бот был добавлен в чат/канал или его статус изменен.")
    print(f"Название: {chat.title}")
    print(f"ID: {chat.id}")
    print("----------------------")

# --- Способ для ГРУПП ---
# Этот обработчик реагирует на любое сообщение в группе.
@bot.message_handler(content_types=['text', 'sticker', 'photo', 'document'])
def handle_group_message(message):
    """
    Получает сообщение из группы и выводит ID в консоль.
    """
    # Проверяем, что это групповой чат, а не личные сообщения
    if message.chat.type in ['group', 'supergroup']:
        chat_id = message.chat.id
        chat_title = message.chat.title

        print("--- Сообщение в группе ---")
        print(f"Название группы: {chat_title}")
        print(f"ID группы: {chat_id}")
        print("------------------------")


if __name__ == '__main__':
    if check_all_apis(bot):
        print("\nБот для определения ID запущен.")
        print("\nДля ГРУППЫ: Напишите любое сообщение в группе.")
        print("Для КАНАЛА: Просто добавьте бота в администраторы канала.")
        print("\nID появится в этой консоли.")
        bot.polling(non_stop=True)
    else:
        print("\nБот не может быть запущен из-за ошибок API.")