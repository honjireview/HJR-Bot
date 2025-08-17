# -*- coding: utf-8 -*-
"""
Обработчики и логика для потока Совета Редакторов.
"""
import logging
import re
from telebot import types
import appealManager
import geminiProcessor
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.council_flow")

CASE_RE = re.compile(r'#\s*(\d{4,7})', re.IGNORECASE)
REPLY_CMD_RE = re.compile(r'/reply\s*#?(\d{4,7})', re.IGNORECASE)

def _extract_case_id_from_text(text: str):
    if not text:
        return None
    m = REPLY_CMD_RE.search(text)
    if m:
        return int(m.group(1))
    m2 = CASE_RE.search(text)
    if m2:
        return int(m2.group(1))
    return None

def finalize_appeal(case_id, bot):
    """
    Завершает апелляцию: получает вердикт от Gemini, обновляет статус
    и отправляет результаты в чаты.
    """
    log.info(f"Начало финального рассмотрения дела #{case_id}")
    appealManager.update_appeal(case_id, "status", "processing")

    verdict = geminiProcessor.get_verdict_from_gemini(case_id)
    appealManager.update_appeal(case_id, "ai_verdict", verdict)
    appealManager.update_appeal(case_id, "status", "closed")

    # Отправка результатов
    try:
        appeal_data = appealManager.get_appeal(case_id)
        applicant_chat_id = appeal_data.get('applicant_chat_id')
        if applicant_chat_id:
            bot.send_message(applicant_chat_id, f"Ваша апелляция #{case_id} рассмотрена.\n\n{verdict}")

        editors_chat_id = resolve_council_id()
        if editors_chat_id:
            bot.send_message(editors_chat_id, f"Дело #{case_id} закрыто.\n\n{verdict}")

        log.info(f"Вердикт по делу #{case_id} успешно отправлен.")
    except Exception as e:
        log.error(f"Ошибка при отправке вердикта по делу #{case_id}: {e}")


def register_council_handlers(bot, user_states):
    @bot.message_handler(commands=['reply'])
    def handle_reply_command(message):
        user_id = message.from_user.id
        case_id = _extract_case_id_from_text(message.text)

        if not case_id:
            bot.reply_to(message, "Пожалуйста, укажите номер дела после команды, например: /reply 12345")
            return

        appeal = appealManager.get_appeal(case_id)
        if not appeal:
            bot.reply_to(message, f"Дело с номером #{case_id} не найдено.")
            return

        user_states[user_id] = {
            "state": "council_awaiting_main_arg",
            "case_id": case_id
        }
        bot.reply_to(message, f"Вы отвечаете по делу #{case_id}. Пожалуйста, изложите ваши основные контраргументы.")

    @bot.message_handler(func=lambda m: str(user_states.get(m.from_user.id, {}).get("state", "")).startswith("council_awaiting_"))
    def handle_council_dialogue(message):
        user_id = message.from_user.id
        state_data = user_states.get(user_id, {})
        state = state_data.get("state")
        case_id = state_data.get("case_id")

        if not case_id:
            _reset_user_state(user_states, user_id)
            return

        responder_info = f"Ответ от {message.from_user.first_name} (@{message.from_user.username})"

        if state == "council_awaiting_main_arg":
            state_data["main_arg"] = message.text
            user_states[user_id]["state"] = "council_awaiting_q1"
            bot.send_message(message.chat.id, "Вопрос 1/2: На каких пунктах устава основано ваше решение?")

        elif state == "council_awaiting_q1":
            state_data["q1"] = message.text
            user_states[user_id]["state"] = "council_awaiting_q2"
            bot.send_message(message.chat.id, "Вопрос 2/2: Как вы оцениваете аргументы заявителя?")

        elif state == "council_awaiting_q2":
            state_data["q2"] = message.text

            answer_data = {
                "responder_info": responder_info,
                "main_arg": state_data.get("main_arg"),
                "q1": state_data.get("q1"),
                "q2": state_data.get("q2")
            }

            appealManager.add_council_answer(case_id, answer_data)
            bot.send_message(message.chat.id, f"Спасибо, ваш ответ по делу #{case_id} принят.")
            user_states.pop(user_id, None)

def _reset_user_state(user_states, user_id):
    user_states.pop(user_id, None)