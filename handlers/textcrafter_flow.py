# -*- coding: utf-8 -*-

import re
from telebot import types

# Глобальный (на уровне модуля) канал для TextCrafter-постинга (аналог bot_data['channel'])
TEXTCRAFTER_CHANNEL = None

# Префиксы команд, чтобы не конфликтовать с другими потоками:
# /craft — старт создания поста
# /tsettings — установка канала по умолчанию для отправки
# /tcancel — отмена
# /tpreview — предпросмотр (доступен в процессе)
CRAFT_CMD = "craft"
TSETTINGS_CMD = "tsettings"
TCANCEL_CMD = "tcancel"
TPREVIEW_CMD = "tpreview"

# Состояния диалога (хранятся в user_states по user_id)
STATE_PHOTO_OR_SKIP = "tc_awaiting_photo_or_skip"
STATE_ADDING_CAPTION = "tc_adding_caption"
STATE_ADDING_BUTTON_TEXT = "tc_adding_button_text"
STATE_ADDING_BUTTON_URL = "tc_adding_button_url"
STATE_ADDING_CHANNEL = "tc_adding_channel"
STATE_SETTING_CHANNEL = "tc_setting_channel"

# Ключ для временных данных текущего диалога
DIALOG_KEY = "tc_dialog"


def _reset_user_state(user_states, user_id: int):
    user_states.pop(user_id, None)


def _ensure_user_bucket(user_states, user_id: int):
    if user_id not in user_states:
        user_states[user_id] = {}
    if DIALOG_KEY not in user_states[user_id]:
        user_states[user_id][DIALOG_KEY] = {}


def _escape_basic_markdown(text: str) -> str:
    # Легкая экранизация некоторых символов, чтобы не рушить Markdown (если понадобится)
    return re.sub(r'([_*`])', r'\\\1', text or "")


def _send_preview(bot, chat_id, dialog):
    photo_file_id = dialog.get('photo_file_id')
    caption = dialog.get('caption') or ""
    button_text = dialog.get('button_text') or "Открыть"
    button_url = dialog.get('button_url') or "https://example.com"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(button_text, url=button_url))

    if photo_file_id:
        bot.send_photo(chat_id, photo=photo_file_id, caption=caption, reply_markup=markup)
    else:
        bot.send_message(chat_id, text=caption or "(пустое сообщение)", reply_markup=markup)


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
    except Exception:
        return False


def register_textcrafter_handlers(bot, user_states):
    """
    Регистрирует обработчики для "TextCrafter" потока постинга в канал.
    Команды:
    - /craft — создать новый пост с кнопкой
    - /tsettings — настроить канал по умолчанию (например, @mychannel или числовой ID)
    - /tpreview — отправить предпросмотр текущего поста в личку
    - /tcancel — отменить текущий диалог
    """

    @bot.message_handler(commands=[CRAFT_CMD])
    def tc_start(message):
        user_id = message.from_user.id
        _reset_user_state(user_states, user_id)
        _ensure_user_bucket(user_states, user_id)

        bot.send_message(
            message.chat.id,
            "Хотите добавить фото к сообщению? Отправьте фото или введите /skip, чтобы пропустить."
        )
        user_states[user_id]['state'] = STATE_PHOTO_OR_SKIP

    @bot.message_handler(commands=[TSETTINGS_CMD])
    def tc_settings(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)

        bot.send_message(
            message.chat.id,
            "Введите имя канала (начиная с @) или числовой ID, куда будут отправляться сообщения по умолчанию."
        )
        user_states[user_id]['state'] = STATE_SETTING_CHANNEL

    @bot.message_handler(commands=[TCANCEL_CMD])
    def tc_cancel(message):
        user_id = message.from_user.id
        _reset_user_state(user_states, user_id)
        bot.send_message(message.chat.id, "Операция отменена.")

    @bot.message_handler(commands=[TPREVIEW_CMD])
    def tc_preview(message):
        user_id = message.from_user.id
        bucket = user_states.get(user_id, {})
        dialog = bucket.get(DIALOG_KEY, {})
        if not dialog or not (dialog.get('photo_file_id') or dialog.get('caption')):
            bot.send_message(message.chat.id, "Нечего предпросматривать. Начните заново через /craft.")
            return
        _send_preview(bot, message.chat.id, dialog)
        bot.send_message(message.chat.id, "Это предпросмотр. Чтобы отправить — укажите канал (если не настроен) сообщением.")

    # Шаг 1: фото или /skip
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('state') == STATE_PHOTO_OR_SKIP, content_types=['photo', 'text'])
    def tc_photo_or_skip(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)
        dialog = user_states[user_id][DIALOG_KEY]

        if message.content_type == 'photo':
            dialog['photo_file_id'] = message.photo[-1].file_id
            bot.send_message(message.chat.id, "Отлично! Теперь введите текст подписи к изображению.")
            user_states[user_id]['state'] = STATE_ADDING_CAPTION
            return

        if message.text and message.text.strip().lower() == '/skip':
            dialog['photo_file_id'] = None
            bot.send_message(message.chat.id, "Хорошо, без фото. Теперь введите текст сообщения.")
            user_states[user_id]['state'] = STATE_ADDING_CAPTION
            return

        bot.send_message(message.chat.id, "Пожалуйста, отправьте фото или введите /skip.")

    # Шаг 2: подпись
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('state') == STATE_ADDING_CAPTION, content_types=['text'])
    def tc_caption(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)
        dialog = user_states[user_id][DIALOG_KEY]

        dialog['caption'] = message.text
        bot.send_message(message.chat.id, "Введите текст для кнопки.")
        user_states[user_id]['state'] = STATE_ADDING_BUTTON_TEXT

    # Шаг 3: текст кнопки
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('state') == STATE_ADDING_BUTTON_TEXT, content_types=['text'])
    def tc_button_text(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)
        dialog = user_states[user_id][DIALOG_KEY]

        dialog['button_text'] = message.text
        bot.send_message(message.chat.id, "Введите URL для кнопки (начиная с http:// или https://).")
        user_states[user_id]['state'] = STATE_ADDING_BUTTON_URL

    # Шаг 4: URL кнопки
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('state') == STATE_ADDING_BUTTON_URL, content_types=['text'])
    def tc_button_url(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)
        dialog = user_states[user_id][DIALOG_KEY]

        url = message.text.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            bot.send_message(message.chat.id, "Некорректный URL. Введите ссылку, начинающуюся с http:// или https://.")
            return

        dialog['button_url'] = url

        # Предпросмотр подсказка и переход к выбору канала
        bot.send_message(
            message.chat.id,
            f"Чтобы увидеть предпросмотр — используйте /{TPREVIEW_CMD}. "
            "Для отправки — введите имя канала (если вы не настроили его через /tsettings)."
        )
        user_states[user_id]['state'] = STATE_ADDING_CHANNEL

    # Шаг 5: отправка в канал (если канал не сохранен глобально)
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('state') == STATE_ADDING_CHANNEL, content_types=['text'])
    def tc_send(message):
        user_id = message.from_user.id
        _ensure_user_bucket(user_states, user_id)
        dialog = user_states[user_id][DIALOG_KEY]

        if not (dialog.get('photo_file_id') or dialog.get('caption')):
            bot.send_message(message.chat.id, "Ошибка: Должно быть фото и/или текст. Начните сначала через /craft.")
            _reset_user_state(user_states, user_id)
            return

        # Канал — либо глобальный, либо указанный пользователем
        global TEXTCRAFTER_CHANNEL
        channel = TEXTCRAFTER_CHANNEL

        if not channel:
            candidate = message.text.strip()
            # Допускаем @channelname или числовой ID
            if candidate.startswith('@'):
                channel = candidate
            else:
                # попробуем как числовой ID
                try:
                    int(candidate)  # проверка, что это число
                    channel = candidate
                except ValueError:
                    bot.send_message(message.chat.id, "Укажите корректный канал: @channelname или числовой ID.")
                    return

        ok = _send_to_channel(bot, channel, dialog)
        if ok:
            bot.send_message(message.chat.id, f"Сообщение отправлено в {channel}.")
        else:
            bot.send_message(
                message.chat.id,
                f"Не удалось отправить сообщение в {channel}. Убедитесь, что бот добавлен и имеет права администратора."
            )

        _reset_user_state(user_states, user_id)

    # Установка канала по умолчанию
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get('state') == STATE_SETTING_CHANNEL, content_types=['text'])
    def tc_set_channel(message):
        global TEXTCRAFTER_CHANNEL
        user_id = message.from_user.id

        candidate = message.text.strip()
        if candidate.startswith('@'):
            TEXTCRAFTER_CHANNEL = candidate
        else:
            try:
                int(candidate)  # проверим, что это число
                TEXTCRAFTER_CHANNEL = candidate
            except ValueError:
                bot.send_message(message.chat.id, "Канал должен быть @username или числовым ID.")
                return

        bot.send_message(message.chat.id, f"Канал по умолчанию сохранен: {TEXTCRAFTER_CHANNEL}")
        _reset_user_state(user_states, user_id)