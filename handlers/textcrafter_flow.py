# -*- coding: utf-8 -*-
"""
Обработчики для "TextCrafter" потока, адаптированные под FSM в БД.
"""
import re
from telebot import types
import logging
import appealManager # Используем наш менеджер состояний

log = logging.getLogger("hjr-bot.textcrafter")

# --- Глобальная переменная для канала по умолчанию (можно заменить на хранение в БД) ---
TEXTCRAFTER_CHANNEL = None

# --- Команды ---
CRAFT_CMD = "craft"
TSETTINGS_CMD = "tsettings"
TCANCEL_CMD = "tcancel"
TPREVIEW_CMD = "tpreview"

# --- Состояния FSM ---
class TCStates:
    PHOTO_OR_SKIP = "tc_photo_or_skip"
    ADDING_CAPTION = "tc_adding_caption"
    ADDING_BUTTON_TEXT = "tc_adding_button_text"
    ADDING_BUTTON_URL = "tc_adding_button_url"
    AWAITING_CHANNEL_FOR_SEND = "tc_awaiting_channel"
    SETTING_DEFAULT_CHANNEL = "tc_setting_channel"

def _send_preview(bot, chat_id, dialog_data):
    photo_file_id = dialog_data.get('photo_file_id')
    caption = dialog_data.get('caption', "")
    button_text = dialog_data.get('button_text')
    button_url = dialog_data.get('button_url')

    markup = None
    if button_text and button_url:
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

def _send_to_channel(bot, channel_id_or_username, dialog_data) -> bool:
    photo_file_id = dialog_data.get('photo_file_id')
    caption = dialog_data.get('caption', "")
    button_text = dialog_data.get('button_text')
    button_url = dialog_data.get('button_url')

    markup = None
    if button_text and button_url:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(button_text, url=button_url))
    try:
        if photo_file_id:
            bot.send_photo(channel_id_or_username, photo=photo_file_id, caption=caption, reply_markup=markup)
        else:
            bot.send_message(channel_id_or_username, text=caption or "(пустое сообщение)", reply_markup=markup)
        return True
    except Exception as e:
        log.error(f"[textcrafter] Send to channel failed for '{channel_id_or_username}': {e}")
        return False

def register_textcrafter_handlers(bot):

    @bot.message_handler(commands=[CRAFT_CMD], chat_types=['private'])
    def tc_start(message):
        user_id = message.from_user.id
        appealManager.set_user_state(user_id, TCStates.PHOTO_OR_SKIP, data={})
        log.info(f"[textcrafter] /craft started by user={user_id}")
        bot.send_message(message.chat.id, "Хотите добавить фото к сообщению? Отправьте фото или введите /skip, чтобы пропустить.")

    @bot.message_handler(commands=[TSETTINGS_CMD], chat_types=['private'])
    def tc_settings(message):
        user_id = message.from_user.id
        appealManager.set_user_state(user_id, TCStates.SETTING_DEFAULT_CHANNEL)
        bot.send_message(message.chat.id, "Введите имя канала (начиная с @) или числовой ID, куда будут отправляться сообщения по умолчанию.")

    @bot.message_handler(commands=[TCANCEL_CMD], chat_types=['private'])
    def tc_cancel(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        if state_data and str(state_data.get('state', '')).startswith('tc_'):
            appealManager.delete_user_state(user_id)
            bot.send_message(message.chat.id, "Операция TextCrafter отменена.")

    @bot.message_handler(commands=[TPREVIEW_CMD], chat_types=['private'])
    def tc_preview(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        if not state_data or not str(state_data.get('state', '')).startswith('tc_'):
            bot.send_message(message.chat.id, "Сейчас не активен процесс создания поста.")
            return
        dialog_data = state_data.get('data', {})
        if not (dialog_data.get('photo_file_id') or dialog_data.get('caption')):
            bot.send_message(message.chat.id, "Нечего предпросматривать. Начните заново через /craft.")
            return
        _send_preview(bot, message.chat.id, dialog_data)

    @bot.message_handler(
        func=lambda m: appealManager.get_user_state(m.from_user.id) is not None and str(appealManager.get_user_state(m.from_user.id).get('state', '')).startswith('tc_') and m.chat.type == 'private',
        content_types=['photo', 'text']
    )
    def tc_state_handler(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        state = state_data.get('state')
        data = state_data.get('data', {})

        if state == TCStates.PHOTO_OR_SKIP:
            if message.content_type == 'photo':
                data['photo_file_id'] = message.photo[-1].file_id
                appealManager.set_user_state(user_id, TCStates.ADDING_CAPTION, data)
                bot.send_message(message.chat.id, "Отлично! Теперь введите текст подписи к изображению.")
            elif message.text and message.text.strip().lower() == '/skip':
                data['photo_file_id'] = None
                appealManager.set_user_state(user_id, TCStates.ADDING_CAPTION, data)
                bot.send_message(message.chat.id, "Хорошо, без фото. Теперь введите текст сообщения.")
            else:
                bot.send_message(message.chat.id, "Пожалуйста, отправьте фото или введите /skip.")

        elif state == TCStates.ADDING_CAPTION:
            data['caption'] = message.text
            appealManager.set_user_state(user_id, TCStates.ADDING_BUTTON_TEXT, data)
            bot.send_message(message.chat.id, "Введите текст для кнопки (или /skip, если кнопка не нужна).")

        elif state == TCStates.ADDING_BUTTON_TEXT:
            if message.text and message.text.strip().lower() == '/skip':
                data['button_text'] = None
                data['button_url'] = None
                appealManager.set_user_state(user_id, TCStates.AWAITING_CHANNEL_FOR_SEND, data)
                bot.send_message(message.chat.id, f"Пост готов. Предпросмотр: /{TPREVIEW_CMD}\nОтправить в канал по умолчанию: /send\nИли введите @channel_name для отправки в другой канал.")
            else:
                data['button_text'] = message.text
                appealManager.set_user_state(user_id, TCStates.ADDING_BUTTON_URL, data)
                bot.send_message(message.chat.id, "Введите URL для кнопки (начиная с http:// или https://).")

        elif state == TCStates.ADDING_BUTTON_URL:
            url = message.text.strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                bot.send_message(message.chat.id, "Некорректный URL. Введите ссылку, начинающуюся с http:// или https://.")
                return
            data['button_url'] = url
            appealManager.set_user_state(user_id, TCStates.AWAITING_CHANNEL_FOR_SEND, data)
            bot.send_message(message.chat.id, f"Пост готов. Предпросмотр: /{TPREVIEW_CMD}\nОтправить в канал по умолчанию: /send\nИли введите @channel_name для отправки в другой канал.")

        elif state == TCStates.AWAITING_CHANNEL_FOR_SEND:
            channel = None
            if message.text and message.text.strip().lower() == '/send':
                global TEXTCRAFTER_CHANNEL
                channel = TEXTCRAFTER_CHANNEL
                if not channel:
                    bot.send_message(message.chat.id, f"Канал по умолчанию не настроен. Настройте его через /{TSETTINGS_CMD} или введите имя канала вручную.")
                    return
            else:
                channel = message.text.strip()

            ok = _send_to_channel(bot, channel, data)
            if ok:
                bot.send_message(message.chat.id, f"Сообщение успешно отправлено в {channel}.")
                appealManager.delete_user_state(user_id)
            else:
                bot.send_message(message.chat.id, f"Не удалось отправить сообщение в {channel}. Убедитесь, что бот добавлен в этот канал и имеет права администратора.")

        elif state == TCStates.SETTING_DEFAULT_CHANNEL:
            candidate = message.text.strip()
            if candidate.startswith('@') or candidate.lstrip('-').isdigit():
                TEXTCRAFTER_CHANNEL = candidate
                bot.send_message(message.chat.id, f"Канал по умолчанию для TextCrafter сохранен: {TEXTCRAFTER_CHANNEL}")
                appealManager.delete_user_state(user_id)
            else:
                bot.send_message(message.chat.id, "Неверный формат. Канал должен быть @username или числовым ID.")