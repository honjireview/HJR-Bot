# -*- coding: utf-8 -*-
"""
Обработчики для команд, связанных с управлением списком редакторов.
"""
import os
import logging
from datetime import datetime, timedelta
import appealManager
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.admin_flow")

# --- Переменная для отслеживания времени последней синхронизации ---
last_sync_time = None

def sync_editors_list(bot):
    """
    Получает список ВСЕХ участников из чата редакторов (кроме ботов) и обновляет БД.
    """
    target_chat = resolve_council_id()
    if not target_chat:
        log.error("[SYNC] Не удалось обновить список: EDITORS_CHANNEL_ID не задан.")
        return 0, "ID чата редакторов не настроен."

    try:
        # get_chat_administrators возвращает только админов.
        # В идеале здесь нужен метод для получения всех участников,
        # но для pyTelegramBotAPI это компромиссное и рабочее решение.
        admins = bot.get_chat_administrators(target_chat)

        editors = [admin for admin in admins if not admin.user.is_bot]
        if not editors:
            return 0, "Не удалось найти администраторов в чате (кроме ботов) для синхронизации."

        appealManager.update_editor_list(editors)
        return len(editors), None
    except Exception as e:
        log.error(f"[SYNC] Ошибка при синхронизации списка редакторов: {e}")
        return 0, str(e)


def register_admin_handlers(bot):
    @bot.message_handler(commands=['sync_editors'], chat_types=['private'])
    def sync_command(message):
        user_id = message.from_user.id

        # --- Проверяем, является ли пользователь редактором ---
        if not appealManager.is_user_an_editor(user_id):
            return # Просто игнорируем, если вызвал не редактор

        global last_sync_time

        # --- Проверяем кулдаун ---
        if last_sync_time and datetime.now() < last_sync_time + timedelta(hours=2):
            remaining_time = (last_sync_time + timedelta(hours=2)) - datetime.now()
            minutes_left = round(remaining_time.total_seconds() / 60)
            log.info(f"[SYNC] Команда /sync_editors на кулдауне для user_id {user_id}. Осталось {minutes_left} мин.")
            bot.reply_to(message, f"Эту команду можно использовать не чаще, чем раз в 2 часа. Пожалуйста, подождите еще примерно {minutes_left} минут.")
            return

        log.info(f"[SYNC] Ручная синхронизация списка редакторов запущена редактором {user_id}.")
        bot.reply_to(message, "Начинаю синхронизацию списка редакторов...")

        count, error = sync_editors_list(bot)

        if error:
            bot.send_message(message.chat.id, f"Во время синхронизации произошла ошибка: {error}")
        else:
            # Обновляем время последней успешной синхронизации
            last_sync_time = datetime.now()
            bot.send_message(message.chat.id, f"Синхронизация завершена. В базу добавлено/обновлено {count} редакторов.")