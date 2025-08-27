# -*- coding: utf-8 -*-
"""
Вспомогательные функции, связанные с каналом/чатом Совета (EDITORS_GROUP_ID).
"""
import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Union

from ..core import appeal_manager as appealManager

log = logging.getLogger("hjr-bot.council_helpers")

# ... (код до request_counter_arguments без изменений) ...
_RESOLVED = {"value": None}

def resolve_council_id() -> Optional[Union[int, str]]:
    """
    Резолвит EDITORS_GROUP_ID из окружения в int (например -100...) или в username '@...'.
    Кеширует результат.
    """
    if _RESOLVED["value"] is not None:
        return _RESOLVED["value"]
    raw = (os.getenv("EDITORS_GROUP_ID") or "").strip()
    if not raw:
        log.warning("[council_helpers] EDITORS_GROUP_ID not set")
        return None
    raw = raw.strip("\"' ")
    if re.fullmatch(r'-?\d+', raw):
        try:
            val = int(raw)
            _RESOLVED["value"] = val
            log.info(f"[council_helpers] resolved to int {val}")
            return val
        except Exception: pass
    if raw.startswith("@") or re.fullmatch(r'[A-Za-z0-9_]{3,}', raw):
        username = raw if raw.startswith("@") else f"@{raw}"
        _RESOLVED["value"] = username
        log.info(f"[council_helpers] resolved to username {username}")
        return username
    log.error(f"[council_helpers] cannot resolve EDITORS_GROUP_ID: '{raw}'")
    return None

def is_link_from_council(bot, parsed_from_chat_id: Union[int, str]) -> bool:
    """
    Проверяет, что parsed_from_chat_id соответствует EDITORS_GROUP_ID.
    """
    resolved = resolve_council_id()
    if not resolved:
        return True
    try:
        if isinstance(resolved, int):
            try:
                return int(parsed_from_chat_id) == resolved
            except Exception: pass
        if isinstance(resolved, str) and str(parsed_from_chat_id).lower() == str(resolved).lower():
            return True
        target_chat = bot.get_chat(resolved)
        parsed_chat = bot.get_chat(parsed_from_chat_id)
        if target_chat and parsed_chat:
            if getattr(target_chat, "id", None) and getattr(parsed_chat, "id", None):
                if int(target_chat.id) == int(parsed_chat.id):
                    return True
    except Exception as ex:
        log.exception(f"[council_helpers] error during council link check: {ex}")
    return False

def request_counter_arguments(bot, case_id: int):
    """
    Формирует и отправляет ПОЛНЫЙ запрос контраргументов по делу case_id в канал/чат Совета.
    Отправляет в нужный топик, если он есть.
    """
    appeal = appealManager.get_appeal(case_id)
    if not appeal:
        log.warning(f"[council_helpers] appeal #{case_id} not found for request_counter_arguments")
        return

    # ... (код формирования request_text без изменений) ...
    decision_text = appeal.get("decision_text") or "(Содержимое оспариваемого решения отсутствует)"
    applicant_args = appeal.get("applicant_arguments") or "(Аргументы заявителя не указаны)"
    answers = appeal.get("applicant_answers") or {}
    q1 = answers.get("q1", "(нет ответа)")
    q2 = answers.get("q2", "(нет ответа)")
    q3 = answers.get("q3", "(нет ответа)")
    bot_username = bot.get_me().username

    request_text = (
        f"📣 *Запрос контраргументов по апелляции №{case_id}* 📣\n\n"
        f"Оспаривается следующее решение:\n"
        f"```\n{decision_text}\n```\n\n"
        f"*Аргументы заявителя (анонимно):*\n"
        f"{applicant_args}\n\n"
        f"*Уточняющие ответы заявителя:*\n"
        f"1. *Нарушенный пункт устава:* {q1}\n"
        f"2. *Справедливый результат:* {q2}\n"
        f"3. *Доп. контекст:* {q3}\n\n"
        f"---"
        f"\n*Инструкция для редакторов:*\n"
        f"Для подачи контраргумента, пожалуйста, перейдите в личный чат с ботом (@{bot_username}) и отправьте ему следующую команду:\n\n"
        f"`/reply {case_id}`\n\n"
        f"*ВАЖНО:* Если в течение 24 часов не будет предоставлено ни одного контраргумента, ИИ-арбитр вынесет решение, основываясь **только на аргументах заявителя**.\n"
        f"_(Срок: 24 часа)_"
    )

    target = resolve_council_id()
    if not target:
        log.error(f"[council_helpers] EDITORS_GROUP_ID not set — cannot send request for case #{case_id}")
        return

    # ИСПРАВЛЕНО: Отправляем в нужный топик
    thread_id = appeal.get("message_thread_id")

    try:
        bot.send_message(target, request_text, parse_mode="Markdown", message_thread_id=thread_id)
        log.info(f"[council_helpers] sent counter-argument request for case #{case_id} to {target}, thread: {thread_id}")
    except Exception as e:
        log.exception(f"[council_helpers] failed to send request for case #{case_id} to {target}: {e}")
        return

    expires_at = datetime.utcnow() + timedelta(hours=24)
    try:
        appealManager.update_appeal(case_id, "timer_expires_at", expires_at)
        log.info(f"[council_helpers] set timer for case #{case_id} at {expires_at.isoformat()}")
    except Exception:
        log.exception(f"[council_helpers] failed to update timer for case #{case_id}")