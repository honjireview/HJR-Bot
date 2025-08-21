# -*- coding: utf-8 -*-
"""
Обработчики для команд, связанных с управлением списком редакторов.
"""
import os
import logging
from datetime import datetime, timedelta
from telebot import types
import appealManager
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.admin_flow")

last_sync_time = None
# Для нового режима /getid
admin_states = {"scanning_user_id": None}

def sync_editors_list(bot):
    # ... (код без изменений) ...
    """
    Получает список администраторов из чата редакторов и обновляет БД.
    Возвращает (количество, сообщение об ошибке или None).
    """
    log.info("--- [SYNC_EDITORS] Начало процесса синхронизации. ---")

    target_chat = resolve_council_id()
    if not target_chat:
        error_msg = "EDITORS_GROUP_ID не задан в переменных окружения."
        log.error(f"[SYNC_EDITORS] ПРОВАЛ: {error_msg}")
        return 0, error_msg

    log.info(f"[SYNC_EDITORS] Шаг 1: ID чата редакторов успешно определён: {target_chat}")

    try:
        log.info(f"[SYNC_EDITORS] Шаг 2: Отправка запроса get_chat_administrators в Telegram API для чата {target_chat}...")
        admins = bot.get_chat_administrators(target_chat)
        log.info(f"[SYNC_EDITORS] Шаг 3: Ответ от API получен. Найдено всего администраторов: {len(admins)}.")

        editors = [admin for admin in admins if not admin.user.is_bot]
        log.info(f"[SYNC_EDITORS] Шаг 4: Отфильтрованы боты. Осталось реальных пользователей (редакторов): {len(editors)}.")

        if not editors:
            error_msg = "В чате не найдено ни одного администратора-человека."
            log.warning(f"[SYNC_EDITORS] ПРОВАЛ: {error_msg}")
            return 0, error_msg

        log.info(f"[SYNC_EDITORS] Шаг 5: Передача {len(editors)} редакторов в appealManager для записи в базу данных...")
        appealManager.update_editor_list(editors)
        log.info("--- [SYNC_EDITORS] УСПЕХ: Процесс синхронизации завершен. ---")
        return len(editors), None

    except Exception as e:
        error_msg = f"Произошла критическая ошибка при вызове Telegram API: {e}"
        log.error(f"[SYNC_EDITORS] КРИТИЧЕСКАЯ ОШИБКА: {error_msg}")
        return 0, error_msg

def register_admin_handlers(bot):
    @bot.message_handler(commands=['sync_editors'], chat_types=['private'])
    def sync_command(message):
        # ... (код без изменений) ...
        user_id = message.from_user.id

        if not appealManager.is_user_an_editor(bot, user_id, resolve_council_id()):
            return

        global last_sync_time

        if last_sync_time and datetime.now() < last_sync_time + timedelta(hours=2):
            remaining_time = (last_sync_time + timedelta(hours=2)) - datetime.now()
            minutes_left = round(remaining_time.total_seconds() / 60)
            bot.reply_to(message, f"Эту команду можно использовать не чаще, чем раз в 2 часа. Пожалуйста, подождите еще примерно {minutes_left} минут.")
            return

        bot.reply_to(message, "Начинаю ручную синхронизацию списка редакторов...")

        count, error = sync_editors_list(bot)

        if error:
            bot.send_message(message.chat.id, f"Во время синхронизации произошла ошибка: {error}")
        else:
            last_sync_time = datetime.now()
            bot.send_message(message.chat.id, f"Синхронизация завершена. В базу добавлено/обновлено {count} редакторов.")

    # ИСПРАВЛЕНО: Новый интерактивный режим /getid
    @bot.message_handler(commands=['getid'], chat_types=['private'])
    def start_get_id_scan(message):
        user_id = message.from_user.id
        if admin_states["scanning_user_id"] is not None:
            bot.reply_to(message, "Режим сканирования уже активирован другим пользователем.")
            return

        admin_states["scanning_user_id"] = user_id
        markup = types.InlineKeyboardMarkup()
        stop_button = types.InlineKeyboardButton("Завершить сканирование", callback_data="stop_get_id_scan")
        markup.add(stop_button)
        bot.send_message(user_id, "Режим сканирования ID активирован.\n\nТеперь добавляйте меня в нужные группы/каналы или назначайте администратором. Я буду присылать их ID сюда.\n\nЧтобы остановить, нажмите кнопку ниже.", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "stop_get_id_scan")
    def stop_get_id_scan(call):
        admin_states["scanning_user_id"] = None
        bot.answer_callback_query(call.id, "Режим сканирования остановлен.")
        bot.edit_message_text("Режим сканирования ID деактивирован.", call.message.chat.id, call.message.message_id)

    @bot.my_chat_member_handler()
    def handle_chat_member_update(update):
        scanning_user = admin_states.get("scanning_user_id")
        if not scanning_user:
            return

        chat = update.chat
        info_text = (
            f"Бот был добавлен/обновлен в чате:\n"
            f"Название: {chat.title}\n"
            f"ID: `{chat.id}`\n"
            f"Тип: {chat.type}"
        )
        bot.send_message(scanning_user, info_text, parse_mode="Markdown")