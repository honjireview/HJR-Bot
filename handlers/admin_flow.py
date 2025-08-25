# honjireview/hjr-bot/HJR-Bot-9aa44cfee942a8142d76d0d46064745fe48346ce/handlers/admin_flow.py
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
admin_states = {"scanning_user_id": None}

def sync_editors_list(bot):
    """
    Получает список администраторов из чата редакторов, определяет их роли и обновляет БД.
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
        log.info(f"[SYNC_EDITORS] Шаг 2: Отправка запроса get_chat_administrators...")
        admins = bot.get_chat_administrators(target_chat)
        log.info(f"[SYNC_EDITORS] Шаг 3: Ответ от API получен. Найдено администраторов: {len(admins)}.")

        editors_with_roles = []
        for admin in admins:
            if admin.user.is_bot:
                continue

            # Определяем роль. По умолчанию 'editor'
            role = 'editor'
            if admin.custom_title and admin.custom_title.lower() == 'исполнитель':
                role = 'executor'
                log.info(f"[SYNC_EDITORS] Обнаружен Исполнитель: {admin.user.username or admin.user.first_name}")

            editors_with_roles.append({
                "user": admin.user,
                "role": role
            })

        log.info(f"[SYNC_EDITORS] Шаг 4: Отфильтрованы боты. Осталось редакторов: {len(editors_with_roles)}.")
        if not editors_with_roles:
            error_msg = "В чате не найдено ни одного администратора-человека."
            log.warning(f"[SYNC_EDITORS] ПРОВАЛ: {error_msg}")
            return 0, error_msg

        log.info(f"[SYNC_EDITORS] Шаг 5: Передача {len(editors_with_roles)} редакторов в appealManager для записи в БД...")
        appealManager.update_editor_list(editors_with_roles)
        log.info("--- [SYNC_EDITORS] УСПЕХ: Процесс синхронизации завершен. ---")
        return len(editors_with_roles), None

    except Exception as e:
        error_msg = f"Произошла критическая ошибка при вызове Telegram API: {e}"
        log.error(f"[SYNC_EDITORS] КРИТИЧЕСКАЯ ОШИБКА: {error_msg}", exc_info=True)
        return 0, error_msg


def register_admin_handlers(bot):
    @bot.message_handler(commands=['sync_editors'], chat_types=['private'])
    def sync_command(message):
        user_id = message.from_user.id
        if not appealManager.is_user_an_editor(bot, user_id, resolve_council_id()):
            return

        global last_sync_time
        if last_sync_time and datetime.now() < last_sync_time + timedelta(hours=2):
            remaining_time = (last_sync_time + timedelta(hours=2)) - datetime.now()
            minutes_left = round(remaining_time.total_seconds() / 60)
            bot.reply_to(message, f"Эту команду можно использовать не чаще, чем раз в 2 часа. Подождите ~{minutes_left} минут.")
            return

        bot.reply_to(message, "Начинаю ручную синхронизацию списка редакторов...")
        count, error = sync_editors_list(bot)
        if error:
            bot.send_message(message.chat.id, f"Ошибка при синхронизации: {error}")
        else:
            last_sync_time = datetime.now()
            bot.send_message(message.chat.id, f"Синхронизация завершена. В базу добавлено/обновлено {count} редакторов.")

    # ... (остальные обработчики без изменений)
    @bot.message_handler(commands=['setstatus'])
    def set_status_command(message):
        # Ограничиваем доступ только для вас (замените на ваш ID)
        if message.from_user.id != 1991732112:
            return

        parts = message.text.split()
        if len(parts) != 3 or not parts[1].startswith('@') or parts[2] not in ['active', 'inactive']:
            bot.reply_to(message, "Неверный формат. Используйте: `/setstatus @username [active/inactive]`")
            return

        username = parts[1][1:] # Убираем @
        status_str = parts[2]

        editor = appealManager.find_editor_by_username(username)
        if not editor:
            bot.reply_to(message, f"Редактор с юзернеймом @{username} не найден в базе данных.")
            return

        user_id = editor['user_id']
        is_inactive = (status_str == 'inactive')

        if appealManager.update_editor_status(user_id, is_inactive):
            bot.reply_to(message, f"Статус для @{username} успешно изменен на '{status_str}'.")
        else:
            bot.reply_to(message, "Произошла ошибка при обновлении статуса.")

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