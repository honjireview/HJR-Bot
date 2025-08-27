# app/handlers/admin.py
# -*- coding: utf-8 -*-
import logging

from datetime import datetime, timedelta
from telebot import types
from app.services import editor_service

log = logging.getLogger("hjr-bot.handlers.admin")

last_sync_time = None
# Состояние для сканирования ID перенесено в сервис, чтобы избежать глобальных переменных
# admin_states = {"scanning_user_id": None}

def register_admin_handlers(bot):
    @bot.message_handler(commands=['sync_editors'], chat_types=['private'])
    def sync_command(message):
        if not editor_service.is_user_an_editor(bot, message.from_user.id):
            return

        global last_sync_time
        if last_sync_time and datetime.now() < last_sync_time + timedelta(hours=2):
            remaining_time = (last_sync_time + timedelta(hours=2)) - datetime.now()
            minutes_left = round(remaining_time.total_seconds() / 60)
            bot.reply_to(message, f"Эту команду можно использовать не чаще, чем раз в 2 часа. Подождите ~{minutes_left} минут.")
            return

        bot.reply_to(message, "Начинаю ручную синхронизацию списка редакторов...")
        count, error = editor_service.sync_editors_list(bot)
        if error:
            bot.send_message(message.chat.id, f"Ошибка при синхронизации: {error}")
        else:
            last_sync_time = datetime.now()
            bot.send_message(message.chat.id, f"Синхронизация завершена. В базу добавлено/обновлено {count} редакторов.")

    @bot.message_handler(commands=['setstatus'])
    def set_status_command(message):
        # Эта команда должна быть защищена. Проверяем, является ли пользователь исполнителем.
        if not editor_service.is_user_executor(bot, message.from_user.id):
            bot.reply_to(message, "Эта команда доступна только Исполнителю.")
            return

        parts = message.text.split()
        if len(parts) != 3 or not parts[1].startswith('@') or parts[2] not in ['active', 'inactive']:
            bot.reply_to(message, "Неверный формат. Используйте: `/setstatus @username [active|inactive]`")
            return

        username = parts[1][1:]
        is_inactive = (parts[2] == 'inactive')

        success, msg = editor_service.set_editor_status_by_username(username, is_inactive)
        bot.reply_to(message, msg)