# -*- coding: utf-8 -*-
"""
Обработчики подачи апелляции с использованием FSM и персистентного хранения состояний в БД.
"""
import logging
import random
from datetime import datetime
from telebot import types

import appealManager
from .telegram_helpers import validate_appeal_link
from .council_helpers import request_counter_arguments

log = logging.getLogger("hjr-bot.applicant_flow")

# --- Машина состояний (FSM) ---
class AppealStates:
    WAITING_FOR_LINK = "waiting_for_link"
    WAITING_VOTE_CONFIRM = "waiting_vote_confirm"
    WAITING_MAIN_ARGUMENT = "waiting_main_argument"
    WAITING_Q1 = "waiting_q1"
    WAITING_Q2 = "waiting_q2"
    WAITING_Q3 = "waiting_q3"

def register_applicant_handlers(bot):

    @bot.message_handler(commands=["start"], chat_types=['private'])
    def send_welcome(message):
        user_id = message.from_user.id
        log.info(f"[FSM] User {user_id} initiated /start. Resetting state.")
        appealManager.delete_user_state(user_id)
        appealManager.log_interaction(user_id, "command_start")
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(
            message.chat.id,
            "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс.",
            reply_markup=markup
        )

    @bot.message_handler(commands=["cancel"], chat_types=['private'])
    def cancel_process(message):
        user_id = message.from_user.id
        state = appealManager.get_user_state(user_id)
        log.info(f"[FSM] User {user_id} initiated /cancel.")
        if state and state.get("data", {}).get("case_id"):
            case_id = state["data"]["case_id"]
            appealManager.delete_appeal(case_id)
            appealManager.log_interaction(user_id, "command_cancel", case_id, "Appeal deleted from DB")
        appealManager.delete_user_state(user_id)
        bot.send_message(message.chat.id, "Процесс подачи апелляции отменен.", reply_markup=types.ReplyKeyboardRemove())

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        appealManager.log_interaction(user_id, "callback_start_appeal")
        appealManager.set_user_state(user_id, AppealStates.WAITING_FOR_LINK)
        log.info(f"[FSM] User {user_id} pressed 'start_appeal'. Set state to WAITING_FOR_LINK.")
        try:
            bot.answer_callback_query(call.id)
        except Exception: pass
        bot.send_message(
            call.message.chat.id,
            "Пожалуйста, пришлите ссылку на сообщение или опрос из канала/группы Совета Редакторов, который вы хотите оспорить."
        )

    @bot.message_handler(
        func=lambda message: appealManager.get_user_state(message.from_user.id) is not None and message.chat.type == 'private',
        content_types=['text']
    )
    def handle_fsm_messages(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        state = state_data.get("state")
        data = state_data.get("data", {})
        case_id = data.get("case_id")
        log.info(f"[FSM] Handling message from user {user_id} in state '{state}'.")

        if state == AppealStates.WAITING_FOR_LINK:
            link = message.text
            is_valid, result = validate_appeal_link(bot, link, user_chat_id=message.chat.id)
            if not is_valid:
                bot.reply_to(message, f"Ошибка: {result}")
                appealManager.log_interaction(user_id, "link_validation_failed", details=f"Link: {link}, Error: {result}")
                return

            appealManager.log_interaction(user_id, "link_validation_success", details=f"Link: {link}")
            content_data = result
            is_poll = content_data.get("type") == "poll"
            new_case_id = random.randint(10000, 99999)
            data["case_id"] = new_case_id
            data["content_data"] = content_data
            initial_appeal_data = {
                "applicant_chat_id": message.chat.id,
                "decision_text": content_data.get("text") or content_data.get("poll", {}).get("question", ""),
                "total_voters": content_data.get("poll", {}).get("total_voter_count"),
                "status": "collecting",
            }
            appealManager.create_appeal(new_case_id, initial_appeal_data)
            appealManager.log_interaction(user_id, "appeal_created", new_case_id)
            bot.send_message(message.chat.id, f"Ссылка принята. Вашему делу присвоен номер #{new_case_id}.")

            if is_poll:
                appealManager.set_user_state(user_id, AppealStates.WAITING_VOTE_CONFIRM, data)
                log.info(f"[FSM] User {user_id}, case #{new_case_id}: Link was a poll. Moving to WAITING_VOTE_CONFIRM.")
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("Да, я голосовал(а)", callback_data=f"vote_yes_{new_case_id}"),
                    types.InlineKeyboardButton("Нет, я не голосовал(а)", callback_data=f"vote_no_{new_case_id}")
                )
                bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
            else:
                appealManager.set_user_state(user_id, AppealStates.WAITING_MAIN_ARGUMENT, data)
                log.info(f"[FSM] User {user_id}, case #{new_case_id}: Link was text. Moving to WAITING_MAIN_ARGUMENT.")
                bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")

        elif state == AppealStates.WAITING_MAIN_ARGUMENT:
            appealManager.update_appeal(case_id, "applicant_arguments", message.text)
            appealManager.set_user_state(user_id, AppealStates.WAITING_Q1, data)
            appealManager.log_interaction(user_id, "submitted_main_argument", case_id)
            log.info(f"[FSM] User {user_id}, case #{case_id}: Got main argument. Moving to WAITING_Q1.")
            bot.send_message(message.chat.id, "Спасибо. Теперь ответьте на уточняющие вопросы.")
            bot.send_message(message.chat.id, "Вопрос 1/3: Какой пункт устава, по вашему мнению, был нарушен?")

        elif state == AppealStates.WAITING_Q1:
            _update_appeal_answer(case_id, "q1", message.text)
            appealManager.set_user_state(user_id, AppealStates.WAITING_Q2, data)
            appealManager.log_interaction(user_id, "submitted_q1", case_id)
            log.info(f"[FSM] User {user_id}, case #{case_id}: Got Q1. Moving to WAITING_Q2.")
            bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")

        elif state == AppealStates.WAITING_Q2:
            _update_appeal_answer(case_id, "q2", message.text)
            appealManager.set_user_state(user_id, AppealStates.WAITING_Q3, data)
            appealManager.log_interaction(user_id, "submitted_q2", case_id)
            log.info(f"[FSM] User {user_id}, case #{case_id}: Got Q2. Moving to WAITING_Q3.")
            bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")

        elif state == AppealStates.WAITING_Q3:
            _update_appeal_answer(case_id, "q3", message.text)
            appealManager.delete_user_state(user_id)
            appealManager.log_interaction(user_id, "submitted_q3_and_finished", case_id)
            log.info(f"[FSM] User {user_id}, case #{case_id}: Got Q3. Dialog finished. Requesting counter-arguments.")
            bot.send_message(message.chat.id, "Спасибо, ваша апелляция полностью оформлена и отправлена на рассмотрение. Вы получите уведомление о вердикте.")
            request_counter_arguments(bot, case_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("vote_"))
    def handle_vote_confirm_callback(call):
        user_id = call.from_user.id
        state_data = appealManager.get_user_state(user_id)
        if not (state_data and state_data.get("state") == AppealStates.WAITING_VOTE_CONFIRM):
            bot.answer_callback_query(call.id, "Это действие уже неактуально.", show_alert=True)
            return

        action, case_id_str = call.data.rsplit('_', 1)
        case_id = int(case_id_str)
        data = state_data.get("data", {})
        log.info(f"[FSM] User {user_id}, case #{case_id}: Responded to vote confirmation with '{action}'.")

        appeal = appealManager.get_appeal(case_id)
        if not appeal:
            bot.answer_callback_query(call.id, "Ошибка: дело не найдено.", show_alert=True)
            return

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

        if action == "vote_yes":
            total_voters = appeal.get("total_voters")
            if total_voters is not None and total_voters > 0:
                appealManager.update_appeal(case_id, "total_voters", total_voters - 1)
            appealManager.log_interaction(user_id, "confirmed_vote", case_id, "Vote count adjusted.")
            bot.send_message(call.message.chat.id, "Понятно. Ваш голос будет вычтен из общего числа для объективности.")
        elif action == "vote_no":
            appealManager.log_interaction(user_id, "denied_vote", case_id)
            bot.send_message(call.message.chat.id, "Понятно. Информация принята.")

        appealManager.set_user_state(user_id, AppealStates.WAITING_MAIN_ARGUMENT, data)
        log.info(f"[FSM] User {user_id}, case #{case_id}: Moving to WAITING_MAIN_ARGUMENT after vote confirm.")
        bot.send_message(call.message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")
        bot.answer_callback_query(call.id)

def _update_appeal_answer(case_id, key, value):
    appeal = appealManager.get_appeal(case_id)
    if appeal:
        current_answers = appeal.get("applicant_answers", {}) or {}
        current_answers[key] = value
        appealManager.update_appeal(case_id, "applicant_answers", current_answers)