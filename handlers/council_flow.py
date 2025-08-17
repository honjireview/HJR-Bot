# -*- coding: utf-8 -*-
"""
Простой обработчик для сообщений в чате/группе редакторов (EDITORS_CHANNEL_ID).
Добавьте вызов register_council_handlers(bot) при инициализации бота.
Он ищет номер дела в тексте (например: "#69868" или "апелляция #69868") или пытается взять case_id
из reply_to_message (если reply_to содержит case id в тексте) — и сохраняет контраргументы в appealManager.
"""
import logging
import re

from .council_helpers import resolve_council_id
import appealManager

log = logging.getLogger("hjr-bot.council_flow_handlers")

CASE_RE = re.compile(r'#\s*(\d{4,7})', re.IGNORECASE)
APEL_RE = re.compile(r'апелляц\w*\s*#\s*(\d{4,7})', re.IGNORECASE)

def _extract_case_id_from_text(text: str):
    if not text:
        return None
    m = APEL_RE.search(text)
    if m:
        return int(m.group(1))
    m2 = CASE_RE.search(text)
    if m2:
        return int(m2.group(1))
    return None

def register_council_handlers(bot):
    @bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'document', 'audio', 'video', 'voice'])
    def _handle_possible_council_message(message):
        try:
            resolved = resolve_council_id()
            # если не настроено — игнорируем
            if not resolved:
                return
            # сравнение по id/username
            chat_id = getattr(message.chat, "id", None)
            chat_username = getattr(message.chat, "username", None)
            match_chat = False
            if isinstance(resolved, int) and chat_id is not None:
                match_chat = (int(chat_id) == int(resolved))
            elif isinstance(resolved, str) and chat_username is not None:
                match_chat = (str(chat_username).lower() == str(resolved).lstrip('@').lower())
            if not match_chat:
                return

            # попытка извлечь case_id из текста сообщения
            case_id = _extract_case_id_from_text(getattr(message, "text", "") or "")
            # если нет в тексте — попробуем взять из reply_to_message (если reply на бот-сообщение, где был case_id)
            if not case_id and getattr(message, "reply_to_message", None):
                case_id = _extract_case_id_from_text(getattr(message.reply_to_message, "text", "") or "")
            if not case_id:
                # не нашли case_id — логируем и проигнорируем
                log.info(f"[council] message in editors chat without case id; id={chat_id} from={getattr(message, 'from_user', None)}")
                return

            # Получаем текст контраргумента: используем text или caption
            counter_text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
            # Сохраняем в appeal
            appeal = appealManager.get_appeal(case_id)
            if not appeal:
                log.info(f"[council] received counterargument for unknown case #{case_id}")
                return
            # Здесь на выбор: добавить в историю, или перезаписать поле
            existing = appeal.get("council_arguments", "") or ""
            if existing:
                new = existing + "\n\n---\n" + counter_text
            else:
                new = counter_text
            appealManager.update_appeal(case_id, "council_arguments", new)
            # Можно обновить статус дела
            appealManager.update_appeal(case_id, "status", "council_responded")
            log.info(f"[council] saved counterarguments for case #{case_id}")
        except Exception:
            log.exception("[council] error handling editors message")