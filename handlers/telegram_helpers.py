# -*- coding: utf-8 -*-
"""
Утилиты по работе с Telegram API.
copy_or_forward_message теперь возвращает dict с извлечённым содержимым сообщения
(если копирование/пересылка прошло успешно), чтобы гарантированно иметь текст/описание/опрос.
"""
import logging
from typing import Optional, Union, Dict, Any

log = logging.getLogger("hjr-bot.telegram_helpers")

def get_chat_safe(bot, chat_id: Union[int, str]):
    try:
        return bot.get_chat(chat_id)
    except Exception as e:
        log.warning(f"[tg] get_chat failed for {chat_id}: {e}")
        return None

def _extract_message_content(message) -> Dict[str, Any]:
    """
    Извлекает из объекта Message основные содержательные поля в удобный словарь.
    Поддерживает: text, caption, poll, media (photo/video/document/voice/audio) captions.
    """
    if not message:
        return {}

    content = {}
    # poll
    poll = getattr(message, "poll", None)
    if poll:
        # сбор информации о poll
        options = []
        try:
            for opt in getattr(poll, "options", []):
                # telebot: option.text, option.voter_count
                options.append({"text": getattr(opt, "text", ""), "voter_count": getattr(opt, "voter_count", 0)})
        except Exception:
            pass
        content["type"] = "poll"
        content["poll"] = {"question": getattr(poll, "question", ""), "options": options, "total_voter_count": getattr(poll, "total_voter_count", None)}
        return content

    # text or caption
    txt = getattr(message, "text", None)
    if not txt:
        txt = getattr(message, "caption", None)
    if txt:
        content["type"] = "text"
        content["text"] = txt

    # media types (we only care about caption if present)
    # presence of attributes: photo, video, document, audio, voice, sticker
    for media_attr in ("photo", "video", "document", "audio", "voice", "sticker"):
        if getattr(message, media_attr, None) is not None:
            content.setdefault("media", []).append(media_attr)
    # Entities / caption_entities are ignored here, but could be added if needed

    # metadata
    try:
        content["message_id"] = getattr(message, "message_id", None)
        content["chat_id"] = getattr(message, "chat", None).id if getattr(message, "chat", None) else None
        content["from_user"] = getattr(message, "from_user", None).id if getattr(message, "from_user", None) else None
        content["raw_message"] = message  # keep raw message object for debug if needed
    except Exception:
        pass

    return content

def copy_or_forward_message(bot, dest_chat_id: Union[int, str], from_chat_id: Union[int, str], message_id: int) -> Optional[Dict[str, Any]]:
    """
    Пытаемся скопировать сообщение в dest_chat_id. Если copy_message упадёт — пробуем forward_message.
    Перед удалением скопированной/пересланной копии извлекаем содержимое и возвращаем словарь:
      {
        "type": "text" | "poll" | "media",
        "text": "...",
        "poll": {...},
        "message_id": ...,
        "chat_id": ...,
        "raw_message": <Message object>
      }
    Возвращаем None при неудаче.
    """
    try:
        copied = bot.copy_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
        content = _extract_message_content(copied)
        # Попытка удалить копию, чтобы не засорять чат пользователя
        try:
            bot.delete_message(chat_id=dest_chat_id, message_id=copied.message_id)
        except Exception:
            # удаление не критично
            log.debug(f"[tg] failed to delete copied message {copied.message_id} in {dest_chat_id}")
        return content
    except Exception as e_copy:
        log.warning(f"[tg] copy_message failed ({from_chat_id}/{message_id}): {e_copy}; trying forward")
        try:
            forwarded = bot.forward_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
            content = _extract_message_content(forwarded)
            try:
                bot.delete_message(chat_id=dest_chat_id, message_id=forwarded.message_id)
            except Exception:
                log.debug(f"[tg] failed to delete forwarded message {forwarded.message_id} in {dest_chat_id}")
            return content
        except Exception as e_forw:
            log.warning(f"[tg] forward_message failed ({from_chat_id}/{message_id}): {e_forw}")
            return None