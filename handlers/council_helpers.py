# -*- coding: utf-8 -*-
"""
Вспомогательные функции, связанные с каналом/чатом Совета (EDITORS_CHANNEL_ID).
Добавлена функция set_council_chat_id_runtime для динамической замены резолв-значения
если бот успешно получил сообщение из другого чата (runtime override).
"""
import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Union

import appealManager

log = logging.getLogger("hjr-bot.council_helpers")

_RESOLVED = {"value": None}

def resolve_council_id() -> Optional[Union[int, str]]:
    """
    Резолвит EDITORS_CHANNEL_ID из окружения в int (например -100...) или в username '@...'.
    Кеширует результат.
    """
    if _RESOLVED["value"] is not None:
        return _RESOLVED["value"]
    raw = (os.getenv("EDITORS_CHANNEL_ID") or "").strip()
    if not raw:
        log.warning("[council_helpers] EDITORS_CHANNEL_ID not set")
        return None
    raw = raw.strip("\"' ")

    # Числовая форма или -100...
    if re.fullmatch(r'-?\d+', raw):
        try:
            val = int(raw)
            _RESOLVED["value"] = val
            log.info(f"[council_helpers] resolved to int {val}")
            return val
        except Exception:
            pass

    # username form
    if raw.startswith("@") or re.fullmatch(r'[A-Za-z0-9_]{3,}', raw):
        username = raw if raw.startswith("@") else f"@{raw}"
        _RESOLVED["value"] = username
        log.info(f"[council_helpers] resolved to username {username}")
        return username

    log.error(f"[council_helpers] cannot resolve EDITORS_CHANNEL_ID: '{raw}'")
    return None

def set_council_chat_id_runtime(chat_id: Union[int, str]):
    """
    Устанавливает runtime-override для резолва EDITORS_CHANNEL_ID.
    Принимает либо int chat_id (например -100...) либо строку '@username'.
    Это позволяет автоматически подстроиться, если переменная окружения была неверной,
    но бот успешно прошёл проверку доступа (copy/forward).
    """
    try:
        if isinstance(chat_id, str):
            s = chat_id.strip()
            # если строка числовая — приведение к int
            if re.fullmatch(r'-?\d+', s):
                val: Union[int, str] = int(s)
            else:
                val = s if s.startswith("@") else f"@{s}"
        else:
            val = int(chat_id)
        _RESOLVED["value"] = val
        log.info(f"[council_helpers] runtime override: resolved set to {val}")
    except Exception as e:
        log.exception(f"[council_helpers] failed to set runtime council id override for {chat_id}: {e}")

def is_link_from_council(bot, parsed_from_chat_id: Union[int, str]) -> bool:
    """
    Проверяет, что parsed_from_chat_id соответствует EDITORS_CHANNEL_ID.
    Если EDITORS_CHANNEL_ID не задан — возвращаем True (нестрогая проверка).
    Сначала пробуем простое сравнение, затем — опционально через bot.get_chat для подтверждения.
    """
    resolved = resolve_council_id()
    if not resolved:
        # Разрешаем любые источники, если не настроено строгое значение
        return True

    try:
        # прямое числовое сравнение
        if isinstance(resolved, int):
            try:
                return int(parsed_from_chat_id) == resolved
            except Exception:
                # parsed может быть строкой '@username' — дальше проверим через API
                pass

        # строковое username == username
        if isinstance(resolved, str) and str(parsed_from_chat_id).lower() == str(resolved).lower():
            return True

        # Попробуем получить объекты через API и сравнить id/username/title
        try:
            target_chat = bot.get_chat(resolved)
        except Exception as e:
            log.debug(f"[council_helpers] get_chat(resolved) failed: {e}")
            target_chat = None

        try:
            parsed_chat = bot.get_chat(parsed_from_chat_id)
        except Exception as e:
            log.debug(f"[council_helpers] get_chat(parsed) failed: {e}")
            parsed_chat = None

        if target_chat and parsed_chat:
            # сравнение по id
            if getattr(target_chat, "id", None) and getattr(parsed_chat, "id", None):
                if int(target_chat.id) == int(parsed_chat.id):
                    return True
            # сравнение по username
            t_un = getattr(target_chat, "username", None)
            p_un = getattr(parsed_chat, "username", None)
            if t_un and p_un and t_un.lower() == p_un.lower():
                return True
            # сравнение по title
            t_title = getattr(target_chat, "title", None)
            p_title = getattr(parsed_chat, "title", None)
            if t_title and p_title and t_title == p_title:
                return True

    except Exception as ex:
        log.exception(f"[council_helpers] error during council link check: {ex}")

    return False

def request_counter_arguments(bot, case_id: int):
    """
    Формирует и отправляет запрос контраргументов по делу case_id в канал/чат Совета.
    Также обновляет поле timer_expires_at в appeal.
    """
    appeal = appealManager.get_appeal(case_id)
    if not appeal:
        log.warning(f"[council_helpers] appeal #{case_id} not found")
        return

    decision_text = appeal.get("decision_text") or "(текст решения отсутствует)"
    applicant_args = appeal.get("applicant_arguments") or "(аргументы заявителя не указаны)"
    answers = appeal.get("applicant_answers") or {}
    q1 = answers.get("q1", "(нет ответа)")
    q2 = answers.get("q2", "(нет ответа)")
    q3 = answers.get("q3", "(нет ответа)")

    request_text = (
        f"📣 *Запрос контраргументов по апелляции №{case_id}* 📣\n\n"
        f"*Решение / содержимое спора:*\n{decision_text}\n\n"
        f"*Аргументы заявителя:*\n{applicant_args}\n\n"
        f"*Уточняющие ответы заявителя:*\n"
        f"1) {q1}\n"
        f"2) {q2}\n"
        f"3) {q3}\n\n"
        f"Пожалуйста, присылайте ваши контраргументы в течение 24 часов. (апелляция #{case_id})"
    )

    target = resolve_council_id()
    if not target:
        log.error(f"[council_helpers] EDITORS_CHANNEL_ID not set — cannot send request for case #{case_id}")
        return

    # Если target — строка с числами, привести к int
    if isinstance(target, str) and re.fullmatch(r'-?\d+', target):
        try:
            target = int(target)
        except Exception:
            pass

    try:
        bot.send_message(target, request_text, parse_mode="Markdown")
        log.info(f"[council_helpers] sent request for case #{case_id} to {target}")
    except Exception as e:
        log.exception(f"[council_helpers] failed to send with Markdown to {target}: {e}; trying without parse_mode")
        try:
            bot.send_message(target, request_text)
            log.info(f"[council_helpers] sent request without parse_mode for case #{case_id} to {target}")
        except Exception as e2:
            log.exception(f"[council_helpers] failed to send request for case #{case_id} to {target}: {e2}")
            return

    expires_at = datetime.utcnow() + timedelta(hours=24)
    try:
        appealManager.update_appeal(case_id, "timer_expires_at", expires_at)
        log.info(f"[council_helpers] set timer for case #{case_id} at {expires_at.isoformat()}")
    except Exception:
        log.exception(f"[council_helpers] failed to update timer for case #{case_id}")