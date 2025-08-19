# -*- coding: utf-8 -*-
import logging
import re
from telebot import types
import appealManager
import geminiProcessor
from .council_helpers import resolve_council_id
from main import COMMIT_HASH

log = logging.getLogger("hjr-bot.council_flow")

REPLY_CMD_RE = re.compile(r'/reply\s*#?(\d{4,7})', re.IGNORECASE)

class CouncilStates:
    AWAITING_MAIN_ARG = "council_awaiting_main_arg"
    AWAITING_Q1 = "council_awaiting_q1"
    AWAITING_Q2 = "council_awaiting_q2"

def finalize_appeal(case_id, bot):
    # ... (код без изменений)
    log.info(f"Начало финального рассмотрения дела #{case_id}")
    appeal = appealManager.get_appeal(case_id)
    if not appeal or appeal.get('status') != 'collecting':
        return

    appealManager.update_appeal(case_id, "status", "processing")

    verdict_log_id = appealManager.log_interaction("SYSTEM", "verdict_generation_started", case_id)
    appealManager.update_appeal(case_id, "verdict_log_id", verdict_log_id)
    appealManager.update_appeal(case_id, "commit_hash", COMMIT_HASH)

    verdict = geminiProcessor.get_verdict_from_gemini(case_id)
    appealManager.update_appeal(case_id, "ai_verdict", verdict)
    appealManager.update_appeal(case_id, "status", "closed")

    try:
        applicant_chat_id = appeal.get('applicant_chat_id')
        if applicant_chat_id:
            bot.send_message(applicant_chat_id, f"Ваша апелляция #{case_id} рассмотрена.\n\n{verdict}")
        editors_chat_id = resolve_council_id()
        if editors_chat_id:
            bot.send_message(editors_chat_id, f"Дело #{case_id} закрыто.\n\n{verdict}")
    except Exception as e:
        log.error(f"Ошибка при отправке вердикта по делу #{case_id}: {e}")

def register_council_handlers(bot):
    @bot.message_handler(commands=['reply'], chat_types=['private'])
    def handle_reply_command(message):
        user_id = message.from_user.id

        # --- ИЗМЕНЕНИЕ: Авторизация по базе данных ---
        if not appealManager.is_user_an_editor(user_id):
            return

        m = REPLY_CMD_RE.search(message.text)
        if not m:
            bot.reply_to(message, "Пожалуйста, укажите номер дела: `/reply 12345`", parse_mode="Markdown")
            return

        case_id = int(m.group(1))
        # ... (остальной код в функции без изменений)
        appeal = appealManager.get_appeal(case_id)
        if not appeal:
            bot.reply_to(message, f"Дело с номером #{case_id} не найдено.")
            return
        if appeal.get('status') != 'collecting':
            bot.reply_to(message, f"Сбор контраргументов по делу #{case_id} уже завершен.")
            return
        appealManager.set_user_state(user_id, CouncilStates.AWAITING_MAIN_ARG, data={"case_id": case_id})
        bot.send_message(user_id, f"Вы отвечаете по делу #{case_id}. Пожалуйста, изложите ваши основные контраргументы.")

    @bot.message_handler(
        func=lambda message: appealManager.get_user_state(message.from_user.id) is not None and str(appealManager.get_user_state(message.from_user.id).get('state', '')).startswith("council_") and message.chat.type == 'private'
    )
    def handle_council_dialogue(message):
        # ... (код в этой функции без изменений)
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        state = state_data.get("state")
        data = state_data.get("data", {})
        case_id = data.get("case_id")
        if not case_id:
            appealManager.delete_user_state(user_id)
            return

        responder_info = f"Ответ от {message.from_user.first_name} (@{message.from_user.username or 'скрыто'})"
        if state == CouncilStates.AWAITING_MAIN_ARG:
            data["main_arg"] = message.text
            appealManager.set_user_state(user_id, CouncilStates.AWAITING_Q1, data)
            bot.send_message(message.chat.id, "Вопрос 1/2: На каких пунктах устава основано ваше решение?")
        elif state == CouncilStates.AWAITING_Q1:
            data["q1"] = message.text
            appealManager.set_user_state(user_id, CouncilStates.AWAITING_Q2, data)
            bot.send_message(message.chat.id, "Вопрос 2/2: Как вы оцениваете аргументы заявителя?")
        elif state == CouncilStates.AWAITING_Q2:
            data["q2"] = message.text
            answer_data = { "responder_info": responder_info, "main_arg": data.get("main_arg"), "q1": data.get("q1"), "q2": data.get("q2") }
            appealManager.add_council_answer(case_id, answer_data)
            appealManager.delete_user_state(user_id)
            bot.send_message(message.chat.id, f"Спасибо, ваш ответ по делу #{case_id} принят.")

            updated_appeal = appealManager.get_appeal(case_id)
            if updated_appeal:
                num_answers = len(updated_appeal.get('council_answers', []))
                expected_responses = updated_appeal.get('expected_responses')
                if expected_responses is not None and num_answers >= expected_responses:
                    finalize_appeal(case_id, bot)