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
        log.warning(f"[tg_helper] get_chat failed for {chat_id}: {e}")
        return None

def _extract_message_content(message) -> Dict[str, Any]:
    if not message:
        return {}
    content = {}
    poll = getattr(message, "poll", None)
    if poll:
        options = []
        try:
            for opt in getattr(poll, "options", []):
                options.append({"text": getattr(opt, "text", ""), "voter_count": getattr(opt, "voter_count", 0)})
        except Exception: pass
        content["type"] = "poll"
        content["poll"] = {"question": getattr(poll, "question", ""), "options": options, "total_voter_count": getattr(poll, "total_voter_count", None)}
        log.debug(f"[_extract] Extracted poll: {content['poll']['question']}")
        return content
    txt = getattr(message, "text", None) or getattr(message, "caption", None)
    if txt:
        content["type"] = "text"
        content["text"] = txt
        log.debug(f"[_extract] Extracted text content.")
    for media_attr in ("photo", "video", "document", "audio", "voice", "sticker"):
        if getattr(message, media_attr, None) is not None:
            content.setdefault("type", "media")
            content.setdefault("media", []).append(media_attr)
            log.debug(f"[_extract] Detected media type: {media_attr}")
    return content

def get_message_content_robust(bot, dest_chat_id: int, from_chat_id: Union[int, str], message_id: int) -> Optional[Dict[str, Any]]:
    """
    Надежный способ получить содержимое сообщения, пробуя разные методы.
    1. Пытается forward_message.
    2. Если не удалось, пытается copy_message.
    В любом случае удаляет временное сообщение.
    """
    temp_message = None
    content = None

    # --- Попытка №1: forward_message ---
    try:
        log.info(f"[ROBUST_GET] Attempting to FORWARD message {message_id} from {from_chat_id} to {dest_chat_id}")
        temp_message = bot.forward_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
        content = _extract_message_content(temp_message)
        log.info(f"[ROBUST_GET] FORWARD successful. Content type: {content.get('type')}")
        return content
    except Exception as e:
        log.warning(f"[ROBUST_GET] FORWARD failed: {e}. Falling back to COPY.")
        # Удаляем временное сообщение, если оно было создано, но извлечение контента провалилось
        if temp_message:
            try:
                bot.delete_message(chat_id=dest_chat_id, message_id=temp_message.message_id)
            except Exception: pass
            temp_message = None

    # --- Попытка №2: copy_message ---
    try:
        log.info(f"[ROBUST_GET] Attempting to COPY message {message_id} from {from_chat_id} to {dest_chat_id}")
        temp_message = bot.copy_message(chat_id=dest_chat_id, from_chat_id=from_chat_id, message_id=message_id)
        content = _extract_message_content(temp_message)
        log.info(f"[ROBUST_GET] COPY successful. Content type: {content.get('type')}")
        return content
    except Exception as e:
        log.error(f"[ROBUST_GET] CRITICAL: Both FORWARD and COPY failed. Last error (COPY): {e}")
        return None
    finally:
        # Гарантированно удаляем временное сообщение
        if temp_message:
            try:
                bot.delete_message(chat_id=dest_chat_id, message_id=temp_message.message_id)
                log.info(f"[ROBUST_GET] Cleanup: Temporary message {temp_message.message_id} deleted from {dest_chat_id}")
            except Exception as del_e:
                log.warning(f"[ROBUST_GET] Cleanup failed for temp message {temp_message.message_id}: {del_e}")


def validate_appeal_link(bot, url: str, user_chat_id: int) -> (bool, Union[str, Dict]):
    """
    Комплексная проверка ссылки для апелляции с исчерпывающим логированием.
    Возвращает (успех, данные/ошибка).
    """
    log.info(f"--- [START VALIDATION] URL: {url}, UserChat: {user_chat_id} ---")

    # Шаг 1: Парсинг ссылки
    parsed_data = parse_message_link(url)
    if not parsed_data:
        log.error("[VALIDATOR] FAILED Step 1: Invalid link format.")
        return False, "Неверный формат ссылки. Убедитесь, что она выглядит как t.me/..."

    from_chat, msg_id = parsed_data
    log.info(f"[VALIDATOR] OK Step 1: Parsed link to ChatID={from_chat}, MessageID={msg_id}")

    # Шаг 2: Проверка принадлежности к каналу Совета
    required_chat = resolve_council_id()
    if required_chat and not is_link_from_council(bot, from_chat):
        log.error(f"[VALIDATOR] FAILED Step 2: Link is not from the editors' channel. Expected: '{required_chat}', Got: '{from_chat}'")
        return False, f"Эта ссылка ведет не на канал редакторов. Ожидался ID, соответствующий '{required_chat}'."
    log.info("[VALIDATOR] OK Step 2: Link belongs to the correct channel.")

    # Шаг 3: Диагностика прав и состояния канала
    try:
        log.info(f"[VALIDATOR] DIAGNOSTIC Step 3: Checking source chat {from_chat}...")
        chat_info = bot.get_chat(from_chat)
        protect_content = getattr(chat_info, 'has_protected_content', False) or getattr(chat_info, 'protect_content', False)
        log.info(f"[VALIDATOR] DIAGNOSTIC: Source chat title: '{chat_info.title}', protect_content flag: {protect_content}")

        bot_member_info = bot.get_chat_member(from_chat, bot.get_me().id)
        log.info(f"[VALIDATOR] DIAGNOSTIC: Bot status in chat {from_chat} is '{bot_member_info.status}'.")
        if bot_member_info.status not in ['administrator', 'member']:
            log.warning(f"[VALIDATOR] DIAGNOSTIC: Bot is not a full member or admin in the source chat. This might cause issues.")
    except Exception as e:
        log.error(f"[VALIDATOR] FAILED DIAGNOSTIC Step 3: Could not get chat info for {from_chat}. Error: {e}")
        return False, "Не удалось проверить права доступа к каналу. Убедитесь, что бот является полноценным участником этого канала."
    log.info("[VALIDATOR] OK Step 3: Diagnostic checks passed.")

    # Шаг 4: Получение содержимого новым надежным методом
    log.info(f"[VALIDATOR] OK Step 4: Attempting to get content using robust method.")
    content = get_message_content_robust(bot, dest_chat_id=user_chat_id, from_chat_id=from_chat, message_id=msg_id)
    if not content:
        log.error("[VALIDATOR] FAILED Step 4: Robust content retrieval failed. Both forward and copy methods were unsuccessful.")
        return False, "Не удалось получить содержимое сообщения. Возможные причины: защита от пересылки у автора оригинального сообщения или защита от копирования в канале. Проверьте логи сервера для деталей."

    log.info(f"[VALIDATOR] OK Step 4: Content extracted successfully. Type: {content.get('type')}")

    # Шаг 5: Проверка на медиа
    if content.get("type") == "media":
        log.warning("[VALIDATOR] FAILED Step 5: Post contains media.")
        return False, "Ссылки на медиафайлы (фото, видео и т.д.) не принимаются. Пожалуйста, укажите ссылку на текстовый пост или опрос."
    log.info("[VALIDATOR] OK Step 5: Content type is valid (text or poll).")

    log.info(f"--- [VALIDATION SUCCESS] URL: {url} ---")
    return True, content