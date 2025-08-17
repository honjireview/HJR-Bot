# -*- coding: utf-8 -*-
"""
Утилиты по работе с Telegram API, чтобы не дублировать try/except в обработчиках.
"""
import logging
from typing import Optional, Union

log = logging.getLogger("hjr-bot.telegram_helpers")

def get_chat_safe(bot, chat_id: Union[int, str]):
    """
    Возвращает объект чата от bot.get_chat или None в случае ошибки.
    """
    try:
        return bot.get_chat(chat_id)
    except Exception as e:
        log.warning(f"[tg] get_chat failed for {chat_id}: {e}")
        return None

def copy_or_forward_message(bot, dest_chat_id: Union[int, str], from_chat_id: Union[int, str], message_id: int):
    """
    Пытаемся скопировать сообщение в dest_chat_id. Если copy_message упадёт
    — пробуем forward_message. Возвращаем Message или None при неудаче.
    """
    try:
        copied = bot.copy_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
        # Не критично, если удаление копии упадёт
        try:
            bot.delete_message(chat_id=dest_chat_id, message_id=copied.message_id)
        except Exception:
            pass
        return copied
    except Exception as e_copy:
        log.warning(f"[tg] copy_message failed ({from_chat_id}/{message_id}): {e_copy}; trying forward")
        try:
            forwarded = bot.forward_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
            try:
                bot.delete_message(chat_id=dest_chat_id, message_id=forwarded.message_id)
            except Exception:
                pass
            return forwarded
        except Exception as e_forw:
            log.warning(f"[tg] forward_message failed ({from_chat_id}/{message_id}): {e_forw}")
            return None