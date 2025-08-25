# -*- coding: utf-8 -*-

import logging
from telebot import types
import appealManager

log = logging.getLogger("hjr-bot.textcrafter")

# --- Ключи и состояния ---
TEXTCRAFTER_PREFIX = "tc_"
STATE_PHOTO_OR_SKIP = f"{TEXTCRAFTER_PREFIX}awaiting_photo_or_skip"
STATE_ADDING_CAPTION = f"{TEXTCRAFTER_PREFIX}adding_caption"
STATE_ADDING_BUTTON_TEXT = f"{TEXTCRAFTER_PREFIX}adding_button_text"
STATE_ADDING_BUTTON_URL = f"{TEXTCRAFTER_PREFIX}adding_button_url"
STATE_AWAITING_FINAL_SENDOFF = f"{TEXTCRAFTER_PREFIX}awaiting_final_sendoff" # Новое состояние для ожидания отправки
STATE_SETTING_CHANNEL = f"{TEXTCRAFTER_PREFIX}setting_channel"

# Ключи для хранения данных в FSM
DIALOG_KEY = "tc_dialog_data"
DEFAULT_CHANNEL_KEY = "tc_default_channel" # Ключ для хранения канала по умолчанию

def _get_default_channel(user_id: int) -> str or None:
    """Получает канал по умолчанию для пользователя из БД."""
    state = appealManager.get_user_state(user_id)
    return state.get("data", {}).get(DEFAULT_CHANNEL_KEY)

def _set_default_channel(user_id: int, channel: str):
    """Сохраняет канал по умолчанию для пользователя в БД."""
    state = appealManager.get_user_state(user_id) or {"state": None, "data": {}}
    state["data"][DEFAULT_CHANNEL_KEY] = channel
    appealManager.set_user_state(user_id, state["state"], state["data"])


def _build_keyboard(dialog_data: dict):
    """Собирает клавиатуру для сообщения с URL-кнопкой."""
    markup = types.InlineKeyboardMarkup()
    if dialog_data.get("button_text") and dialog_data.get("button_url"):
        button = types.InlineKeyboardButton(text=dialog_data["button_text"], url=dialog_data["button_url"])
        markup.add(button)
    return markup

def _send_preview(bot, chat_id: int, dialog_data: dict):
    """
    Отправляет предпросмотр сообщения пользователю в личный чат.
    """
    log.info(f"[TextCrafter] Sending preview to chat_id={chat_id}")
    caption = dialog_data.get("caption", "Нет текста.")
    photo_id = dialog_data.get("photo_file_id")
    markup = _build_keyboard(dialog_data)

    try:
        if photo_id:
            bot.send_photo(chat_id, photo_id, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        log.info(f"[TextCrafter] Preview sent successfully to chat_id={chat_id}")
    except Exception as e:
        log.error(f"[TextCrafter] Failed to send preview to chat_id={chat_id}. Error: {e}")
        bot.send_message(chat_id, f"Не удалось отправить предпросмотр. Ошибка: {e}")

def _send_to_channel(bot, channel_id_or_username: str, dialog_data: dict) -> bool:
    """
    Отправляет финальное сообщение в указанный канал.
    """
    log.info(f"[TextCrafter] Attempting to send message to channel='{channel_id_or_username}'")
    caption = dialog_data.get("caption", "")
    photo_id = dialog_data.get("photo_file_id")
    markup = _build_keyboard(dialog_data)

    try:
        if photo_id:
            bot.send_photo(channel_id_or_username, photo_id, caption=caption, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(channel_id_or_username, caption, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        log.info(f"[TextCrafter] Message successfully sent to channel='{channel_id_or_username}'")
        return True
    except Exception as e:
        log.error(f"[TextCrafter] Failed to send message to channel='{channel_id_or_username}'. Error: {e}")
        return False

def register_textcrafter_handlers(bot):
    """
    Регистрирует обработчики для "TextCrafter" потока.
    """

    @bot.message_handler(commands=["craft"])
    def tc_start(message):
        user_id = message.from_user.id
        log.info(f"[TextCrafter] /craft command received from user_id={user_id}")
        appealManager.set_user_state(user_id, STATE_PHOTO_OR_SKIP, {"data": {DIALOG_KEY: {}}})
        bot.send_message(message.chat.id, "Начинаем создание поста.\n\nШаг 1: Отправьте фото для поста или введите /skip, чтобы пропустить.")

    @bot.message_handler(commands=["tsettings"])
    def tc_settings(message):
        user_id = message.from_user.id
        log.info(f"[TextCrafter] /tsettings command received from user_id={user_id}")
        appealManager.set_user_state(user_id, STATE_SETTING_CHANNEL, {"data": appealManager.get_user_state(user_id).get("data", {})})
        default_channel = _get_default_channel(user_id)
        msg = f"Текущий канал по умолчанию: `{default_channel}`\n\n" if default_channel else "Канал по умолчанию не задан.\n\n"
        bot.send_message(message.chat.id, msg + "Пожалуйста, введите ID канала (например, `-100...`) или его юзернейм (например, `@channel_name`), который будет использоваться для отправки постов.", parse_mode="Markdown")

    @bot.message_handler(commands=["tpreview"])
    def tc_preview(message):
        user_id = message.from_user.id
        log.info(f"[TextCrafter] /tpreview command received from user_id={user_id}")
        state_data = appealManager.get_user_state(user_id)
        if not state_data:
            bot.send_message(message.chat.id, "Нет активного процесса создания поста. Начните с /craft.")
            return

        dialog_data = state_data.get("data", {}).get(DIALOG_KEY, {})
        if not (dialog_data.get('photo_file_id') or dialog_data.get('caption')):
            bot.send_message(message.chat.id, "Нечего предпросматривать. Вы еще не добавили ни фото, ни текста.")
            return

        _send_preview(bot, message.chat.id, dialog_data)

    @bot.message_handler(
        func=lambda m: str(appealManager.get_user_state(m.from_user.id).get('state', '')).startswith(TEXTCRAFTER_PREFIX),
        content_types=['photo', 'text']
    )
    def tc_state_handler(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        state = state_data.get("state")
        data = state_data.get("data", {})
        dialog_data = data.get(DIALOG_KEY, {})
        log.info(f"[TextCrafter] Handling state '{state}' for user_id={user_id}")

        # Обработка команд /skip и /cancel внутри FSM
        if message.content_type == 'text' and message.text.startswith('/'):
            if message.text.lower().strip() == '/skip':
                if state == STATE_PHOTO_OR_SKIP:
                    log.info(f"[TextCrafter] User {user_id} skipped photo.")
                    dialog_data['photo_file_id'] = None
                    data[DIALOG_KEY] = dialog_data
                    appealManager.set_user_state(user_id, STATE_ADDING_CAPTION, data)
                    bot.send_message(message.chat.id, "Шаг 2: Введите текст (описание) для вашего поста. Можно использовать Markdown-разметку.")
                else:
                    bot.reply_to(message, "Команду /skip можно использовать только на шаге добавления фото.")
                return
            # /cancel обрабатывается глобальным хендлером, здесь можно не дублировать
            return


        if state == STATE_PHOTO_OR_SKIP:
            if message.content_type == 'photo':
                dialog_data['photo_file_id'] = message.photo[-1].file_id
                data[DIALOG_KEY] = dialog_data
                appealManager.set_user_state(user_id, STATE_ADDING_CAPTION, data)
                log.info(f"[TextCrafter] User {user_id} added a photo.")
                bot.send_message(message.chat.id, "Отлично! Фото добавлено.\n\nШаг 2: Теперь введите текст (описание) для вашего поста. Можно использовать Markdown-разметку.")
            else:
                bot.send_message(message.chat.id, "Пожалуйста, отправьте фото или введите /skip.")

        elif state == STATE_ADDING_CAPTION:
            dialog_data['caption'] = message.text
            data[DIALOG_KEY] = dialog_data
            appealManager.set_user_state(user_id, STATE_ADDING_BUTTON_TEXT, data)
            log.info(f"[TextCrafter] User {user_id} added caption.")
            bot.send_message(message.chat.id, "Шаг 3: Введите текст для URL-кнопки (например, 'Читать далее'). Если кнопка не нужна, введите /skip.")

        elif state == STATE_ADDING_BUTTON_TEXT:
            if message.text.lower().strip() == '/skip':
                dialog_data['button_text'] = None
                dialog_data['button_url'] = None
                data[DIALOG_KEY] = dialog_data
                appealManager.set_user_state(user_id, STATE_AWAITING_FINAL_SENDOFF, data)
                log.info(f"[TextCrafter] User {user_id} skipped button creation.")
                bot.send_message(message.chat.id, "Пост готов к отправке.")
                # Сразу переходим к отправке
                tc_handle_sendoff(message, user_id, state_data)
                return

            dialog_data['button_text'] = message.text
            data[DIALOG_KEY] = dialog_data
            appealManager.set_user_state(user_id, STATE_ADDING_BUTTON_URL, data)
            log.info(f"[TextCrafter] User {user_id} added button text.")
            bot.send_message(message.chat.id, "Шаг 4: Теперь введите полную ссылку (URL) для кнопки, начиная с `http://` или `https://`.")

        elif state == STATE_ADDING_BUTTON_URL:
            url = message.text.strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                bot.send_message(message.chat.id, "Ошибка. URL должен начинаться с `http://` или `https://`. Попробуйте еще раз.")
                return
            dialog_data['button_url'] = url
            data[DIALOG_KEY] = dialog_data
            appealManager.set_user_state(user_id, STATE_AWAITING_FINAL_SENDOFF, data)
            log.info(f"[TextCrafter] User {user_id} added button URL. Post is complete.")
            bot.send_message(message.chat.id, "Отлично! Пост полностью готов.")
            tc_handle_sendoff(message, user_id, state_data)


        elif state == STATE_AWAITING_FINAL_SENDOFF:
            tc_handle_sendoff(message, user_id, state_data)


        elif state == STATE_SETTING_CHANNEL:
            candidate = message.text.strip()
            if candidate.startswith('@') or (candidate.startswith('-') and candidate[1:].isdigit()):
                _set_default_channel(user_id, candidate)
                log.info(f"[TextCrafter] User {user_id} set new default channel: {candidate}")
                bot.send_message(message.chat.id, f"Канал по умолчанию успешно сохранен: `{candidate}`", parse_mode="Markdown")
                appealManager.delete_user_state(user_id) # Выходим из FSM
            else:
                bot.send_message(message.chat.id, "Неверный формат. Канал должен быть юзернеймом (`@username`) или числовым ID (начинаться с `-`).")

    def tc_handle_sendoff(message, user_id, state_data):
        """Внутренняя функция для обработки отправки поста"""
        default_channel = _get_default_channel(user_id)
        dialog_data = state_data.get("data", {}).get(DIALOG_KEY, {})

        if default_channel:
            log.info(f"[TextCrafter] Found default channel '{default_channel}' for user {user_id}. Attempting to send.")
            ok = _send_to_channel(bot, default_channel, dialog_data)
            if ok:
                bot.send_message(message.chat.id, f"Сообщение успешно отправлено в канал по умолчанию ({default_channel}).")
                appealManager.delete_user_state(user_id)
            else:
                bot.send_message(message.chat.id, f"Не удалось отправить сообщение в канал по умолчанию ({default_channel}). Проверьте, что бот добавлен в канал и имеет права на публикацию. Вы можете попробовать отправить в другой канал, указав его ID или юзернейм.")
        else:
            log.info(f"[TextCrafter] Default channel not found for user {user_id}. Asking for channel.")
            bot.send_message(message.chat.id, "Используйте /tpreview для предпросмотра.\n\nЧтобы отправить пост, введите ID или юзернейм канала (например, `@my_channel` или `-100...`).")

    @bot.message_handler(
        func=lambda m: appealManager.get_user_state(m.from_user.id) and appealManager.get_user_state(m.from_user.id).get('state') == STATE_AWAITING_FINAL_SENDOFF,
        content_types=['text']
    )
    def tc_send_to_specific_channel(message):
        user_id = message.from_user.id
        channel_input = message.text.strip()
        log.info(f"[TextCrafter] User {user_id} provided specific channel to send: '{channel_input}'")

        state_data = appealManager.get_user_state(user_id)
        dialog_data = state_data.get("data", {}).get(DIALOG_KEY, {})

        if not dialog_data:
            bot.send_message(message.chat.id, "Произошла ошибка, данные поста не найдены. Пожалуйста, начните заново с /craft.")
            appealManager.delete_user_state(user_id)
            return

        ok = _send_to_channel(bot, channel_input, dialog_data)
        if ok:
            bot.send_message(message.chat.id, f"Сообщение успешно отправлено в {channel_input}.")
            appealManager.delete_user_state(user_id)
        else:
            bot.send_message(message.chat.id, f"Не удалось отправить сообщение в {channel_input}. Убедитесь, что ID/юзернейм верны, и бот добавлен в канал с правами администратора.")