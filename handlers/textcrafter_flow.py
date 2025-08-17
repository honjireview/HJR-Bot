# -*- coding: utf-8 -*-

import re
from telebot import types
import logging

log = logging.getLogger("hjr-bot")

TEXTCRAFTER_CHANNEL = None

CRAFT_CMD = "craft"
TSETTINGS_CMD = "tsettings"
TCANCEL_CMD = "tcancel"
TPREVIEW_CMD = "tpreview"

STATE_PHOTO_OR_SKIP = "tc_awaiting_photo_or_skip"
STATE_ADDING_CAPTION = "tc_adding_caption"
STATE_ADDING_BUTTON_TEXT = "tc_adding_button_text"
STATE_ADDING_BUTTON_URL = "tc_adding_button_url"
STATE_ADDING_CHANNEL = "tc_adding_channel"
STATE_SETTING_CHANNEL = "tc_setting_channel"

DIALOG_KEY = "tc_dialog"

def _reset_user_state(user_states, user_id: int):
    user_states.pop(user_id, None)

def _ensure_user_bucket(user_states, user_id: int):
    if user_id not in user_states:
        user_states[user_id] = {}
    if DIALOG_KEY not in user_states[user_id]:
        user_states[user_id][DIALOG_KEY] = {}

def _send_preview(bot, chat_id, dialog):
    photo_file_id = dialog.get('photo_file_id')
    caption = dialog.get('caption') or ""
    button_text = dialog.get('button_text') or "Открыть"
    button_url = dialog.get('button_url') or "https://example.com"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(button_text, url=button_url))

    try:
        if photo_file_id:
            bot.send_photo(chat_id, photo=photo_file_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(chat_id, text=caption or "(пустое сообщение)", reply_markup=markup)
    except Exception as e:
        log.error(f"[textcrafter] Preview failed: {e}")
        bot.send_message(chat_id, "Не удалось отправить предпросмотр.")

def _send_to_channel(bot, channel_id_or_username, dialog) -> bool:
    photo_file_id = dialog.get('photo_file_id')
    caption = dialog.get('caption') or ""
    button_text = dialog.get('button_text') or "Открыть"
    button_url = dialog.get('button_url') or "https://example.com"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(button_text, url=button_url))

    try:
        if photo_file_id:
            bot.send_photo(channel_id_or_username, photo=photo_file_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(channel_id_or_username, text=caption or "(пустое сообщение)", reply_markup=markup)
        return True
    except Exception as e:
        log.error(f"[textcrafter] Send to channel failed: {e}")
        return False

def register_textcrafter_handlers(bot, user_states):
    """
    Регистрирует обработчики для "TextCrafter" потока.
    """

    @bot.message_handler(commands=[CRAFT_CMD])
    def tc_start(message):
        user_id = message.from_user.id
        _reset_user_state(user_states, user_id)
        _ensure_user_bucket(user_states, user_id)
        log.info(f"[textcrafter] /craft started by user={user_id}")
        bot.send_message(message.chat.id, "Хотите добавить фото к сообщению? Отправьте фото или введите /skip, чтобы пропустить.")
        user_states[user_id]['state'] = STATE_PHOTO_OR_SKIP

    @bot.message_handler(commands=[TSETTINGS_CMD])
    def tc_settings(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)
        bot.send_message(message.chat.id, "Введите имя канала (начиная с @) или числовой ID, куда будут отправляться сообщения по умолчанию.")
        user_states[user_id]['state'] = STATE_SETTING_CHANNEL

    @bot.message_handler(commands=[TCANCEL_CMD])
    def tc_cancel(message):
        user_id = message.from_user.id
        if str(user_states.get(user_id, {}).get('state', '')).startswith('tc_'):
            _reset_user_state(user_states, user_id)
            bot.send_message(message.chat.id, "Операция TextCrafter отменена.")

    @bot.message_handler(commands=[TPREVIEW_CMD])
    def tc_preview(message):
        user_id = message.from_user.id
        bucket = user_states.get(user_id, {})
        dialog = bucket.get(DIALOG_KEY, {})
        if not dialog or not (dialog.get('photo_file_id') or dialog.get('caption')):
            bot.send_message(message.chat.id, "Нечего предпросматривать. Начните заново через /craft.")
            return
        _send_preview(bot, message.chat.id, dialog)

    # Единый обработчик для всех состояний TextCrafter
    @bot.message_handler(
        func=lambda m: str(user_states.get(m.from_user.id, {}).get('state', '')).startswith('tc_'),
        content_types=['photo', 'text']
    )
    def tc_state_handler(message):
        user_id = message.from_user.id
        state_data = user_states.get(user_id, {})
        state = state_data.get('state')
        dialog = state_data.get(DIALOG_KEY, {})

        if state == STATE_PHOTO_OR_SKIP:
            if message.content_type == 'photo':
                dialog['photo_file_id'] = message.photo[-1].file_id
                bot.send_message(message.chat.id, "Отлично! Теперь введите текст подписи к изображению.")
                user_states[user_id]['state'] = STATE_ADDING_CAPTION
            elif message.text and message.text.strip().lower() == '/skip':
                dialog['photo_file_id'] = None
                bot.send_message(message.chat.id, "Хорошо, без фото. Теперь введите текст сообщения.")
                user_states[user_id]['state'] = STATE_ADDING_CAPTION
            else:
                bot.send_message(message.chat.id, "Пожалуйста, отправьте фото или введите /skip.")

        elif state == STATE_ADDING_CAPTION:
            dialog['caption'] = message.text
            bot.send_message(message.chat.id, "Введите текст для кнопки.")
            user_states[user_id]['state'] = STATE_ADDING_BUTTON_TEXT

        elif state == STATE_ADDING_BUTTON_TEXT:
            dialog['button_text'] = message.text
            bot.send_message(message.chat.id, "Введите URL для кнопки (начиная с http:// или https://).")
            user_states[user_id]['state'] = STATE_ADDING_BUTTON_URL

        elif state == STATE_ADDING_BUTTON_URL:
            url = message.text.strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                bot.send_message(message.chat.id, "Некорректный URL. Введите ссылку, начинающуюся с http:// или https://.")
                return
            dialog['button_url'] = url
            bot.send_message(message.chat.id, f"Чтобы увидеть предпросмотр — используйте /{TPREVIEW_CMD}. Для отправки — введите имя канала (если не настроен).")
            user_states[user_id]['state'] = STATE_ADDING_CHANNEL

        elif state == STATE_ADDING_CHANNEL:
            global TEXTCRAFTER_CHANNEL
            channel = TEXTCRAFTER_CHANNEL or message.text.strip()
            ok = _send_to_channel(bot, channel, dialog)
            if ok:
                bot.send_message(message.chat.id, f"Сообщение отправлено в {channel}.")
            else:
                bot.send_message(message.chat.id, f"Не удалось отправить сообщение в {channel}. Убедитесь, что бот добавлен и имеет права администратора.")
            _reset_user_state(user_states, user_id)

        elif state == STATE_SETTING_CHANNEL:
            candidate = message.text.strip()
            if candidate.startswith('@') or candidate.lstrip('-').isdigit():
                TEXTCRAFTER_CHANNEL = candidate
                bot.send_message(message.chat.id, f"Канал по умолчанию сохранен: {TEXTCRAFTER_CHANNEL}")
                _reset_user_state(user_states, user_id)
            else:
                bot.send_message(message.chat.id, "Канал должен быть @username или числовым ID.")