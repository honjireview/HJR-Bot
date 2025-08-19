# -*- coding: utf-8 -*-
"""
Утилиты по работе с Telegram API.
"""
import logging
from typing import Optional, Union, Dict, Any

from .parse_link import parse_message_link
from .council_helpers import is_link_from_council, resolve_council_id

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
    """
    if not message:
        return {}

    content = {}
    poll = getattr(message, "poll", None)
    if poll:
        options = []
        try:
            for opt in getattr(poll, "options", []):
                options.append({"text": getattr(opt, "text", ""), "voter_count": getattr(opt, "voter_count", 0)})
        except Exception:
            pass
        content["type"] = "poll"
        content["poll"] = {"question": getattr(poll, "question", ""), "options": options, "total_voter_count": getattr(poll, "total_voter_count", None)}
        return content

    txt = getattr(message, "text", None) or getattr(message, "caption", None)
    if txt:
        content["type"] = "text"
        content["text"] = txt

    for media_attr in ("photo", "video", "document", "audio", "voice", "sticker"):
        if getattr(message, media_attr, None) is not None:
            content.setdefault("type", "media")
            content.setdefault("media", []).append(media_attr)

    return content

def copy_and_extract_message(bot, dest_chat_id: Union[int, str], from_chat_id: Union[int, str], message_id: int) -> Optional[Dict[str, Any]]:
    """
    Копирует сообщение в dest_chat_id (безопасное место), извлекает содержимое и немедленно удаляет копию.
    Возвращает словарь с содержимым или None при неудаче.
    """
    copied_message = None
    try:
        copied_message = bot.copy_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
        content = _extract_message_content(copied_message)
        return content
    except Exception as e:
        log.error(f"[tg] copy_message failed ({from_chat_id}/{message_id}) -> {dest_chat_id}: {e}")
        return None
    finally:
        # Гарантированно пытаемся удалить временное сообщение, чтобы не спамить пользователю
        if copied_message:
            try:
                bot.delete_message(chat_id=dest_chat_id, message_id=copied_message.message_id)
            except Exception:
                # Ошибка удаления не критична
                pass


def validate_appeal_link(bot, url: str, user_chat_id: int) -> (bool, Union[str, Dict]):
    """
    Комплексная проверка ссылки для апелляции.
    Использует чат с пользователем как временное место для копирования сообщения.
    Возвращает (успех, данные/ошибка).
    """
    # Шаг 1: Парсинг ссылки
    parsed_data = parse_message_link(url)
    if not parsed_data:
        return False, "Неверный формат ссылки. Убедитесь, что она выглядит как t.me/..."

    from_chat, msg_id = parsed_data

    # Шаг 2: Проверка принадлежности к каналу Совета
    required_chat = resolve_council_id()
    if required_chat and not is_link_from_council(bot, from_chat):
        return False, f"Эта ссылка ведет не на канал редакторов. Ожидался ID, соответствующий '{required_chat}'."

    # Шаг 3: Получение содержимого через безопасное копирование
    content = copy_and_extract_message(bot, dest_chat_id=user_chat_id, from_chat_id=from_chat, message_id=msg_id)
    if not content:
        return False, "Не удалось получить содержимое сообщения. Убедитесь, что бот добавлен в канал/группу и имеет права на чтение сообщений."

    # Шаг 4: Проверка на медиа
    if content.get("type") == "media":
        return False, "Ссылки на медиафайлы (фото, видео и т.д.) не принимаются. Пожалуйста, укажите ссылку на текстовый пост или опрос."

    # Все проверки пройдены
    return True, content