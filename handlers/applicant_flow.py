# -*- coding: utf-8 -*-
"""
Обработчики подачи апелляции с финальными исправлениями и улучшениями.
"""
import logging
import random
from datetime import datetime
from telebot import types

import appealManager
from .telegram_helpers import validate_appeal_link
from .council_helpers import request_counter_arguments

log = logging.getLogger("hjr-bot.applicant_flow")
CHARACTER_LIMIT = 4000

class AppealStates:
    WAITING_FOR_LINK = "waiting_for_link"
    WAITING_VOTE_CONFIRM = "waiting_vote_confirm"
    WAITING_MAIN_ARGUMENT = "waiting_main_argument"
    WAITING_Q1 = "waiting_q1"
    WAITING_Q2 = "waiting_q2"
    WAITING_Q3 = "waiting_q3"

def _render_item_text(item: dict) -> str:
    if not item: return ""
    if item.get("type") == "poll":
        p = item.get("poll", {})
        q = p.get("question", "")
        opts = p.get("options", [])
        opts_text = "\n".join([f"- {o.get('text', '')}: {o.get('voter_count', 0)} голосов" for o in opts])
        total = p.get('total_voter_count')
        total_text = f"\nВсего проголосовало: {total}" if total is not None else ""
        return f"Опрос: {q}\n{opts_text}{total_text}"
    if item.get("type") == "text":
        return item.get("text", "")
    return "(Не удалось отобразить содержимое)"

def register_applicant_handlers(bot):
    @bot.message_handler(commands=["start"], chat_types=['private'])
    def send_welcome(message):
        user_id = message.from_user.id
        is_editor = appealManager.is_user_an_editor(bot, user_id)
        log.info(f"[AUTH] User {user_id} initiated /start. Editor status: {is_editor}.")

        if not is_editor:
            bot.send_message(message.chat.id, "Эта функция доступна только для авторизованных участников Совета Редакторов.")
            return

        if appealManager.get_user_state(user_id) is not None:
            bot.send_message(message.chat.id, "Вы уже находитесь в процессе. Чтобы начать заново, отмените его: /cancel.")
            return

        appealManager.delete_user_state(user_id)
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(message.chat.id, "Здравствуйте! Это бот для подачи апелляций...", reply_markup=markup)

    @bot.message_handler(commands=["cancel"], chat_types=['private'])
    def cancel_process(message):
        user_id = message.from_user.id
        state = appealManager.get_user_state(user_id)
        if state and state.get("data", {}).get("case_id"):
            case_id = state["data"]["case_id"]
            appealManager.delete_appeal(case_id)
        appealManager.delete_user_state(user_id)
        bot.send_message(message.chat.id, "Процесс подачи апелляции отменен.")

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        is_editor = appealManager.is_user_an_editor(bot, user_id)
        log.info(f"[AUTH] User {user_id} pressed 'start_appeal' button. Editor status: {is_editor}.")

        if not is_editor:
            bot.answer_callback_query(call.id, "Эта функция доступна только для авторизованных участников Совета Редакторов.", show_alert=True)
            return

        active_case = appealManager.get_active_appeal_by_user(user_id)
        if active_case:
            log.warning(f"[FSM] User {user_id} tried to start a new appeal while case #{active_case} is active.")
            bot.answer_callback_query(call.id, f"Вы не можете подать новую апелляцию, пока активна ваша предыдущая (дело #{active_case}).", show_alert=True)
            return

        appealManager.set_user_state(user_id, AppealStates.WAITING_FOR_LINK)
        log.info(f"[FSM] User {user_id} is authorized and has no active cases. Set state to WAITING_FOR_LINK.")
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Пожалуйста, пришлите ссылку на сообщение или опрос...")

    @bot.message_handler(
        func=lambda message: (
                appealManager.get_user_state(message.from_user.id) is not None and
                not str(appealManager.get_user_state(message.from_user.id).get('state', '')).startswith("council_") and
                message.chat.type == 'private'
        ),
        content_types=['text']
    )
    def handle_fsm_messages(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        state = state_data.get("state")
        data = state_data.get("data", {})

        if len(message.text) > CHARACTER_LIMIT:
            bot.reply_to(message, "Вы превысили лимит символов (4000). Это сделано для защиты от спама...")
            return

        if state == AppealStates.WAITING_FOR_LINK:
            is_valid, result = validate_appeal_link(bot, message.text, user_chat_id=message.chat.id)
            if not is_valid:
                bot.reply_to(message, f"Ошибка: {result}")
                return
            content_data = result
            new_case_id = random.randint(10000, 99999)
            data["case_id"] = new_case_id

            applicant_info = { "id": user_id, "first_name": message.from_user.first_name, "username": message.from_user.username }
            initial_appeal_data = {
                "applicant_chat_id": message.chat.id, "applicant_info": applicant_info,
                "created_at": datetime.utcnow(), "decision_text": _render_item_text(content_data),
                "total_voters": content_data.get("poll", {}).get("total_voter_count"), "status": "collecting",
            }
            appealManager.create_appeal(new_case_id, initial_appeal_data)
            bot.send_message(message.chat.id, f"Ссылка принята. Вашему делу присвоен номер #{new_case_id}.")

            if content_data.get("type") == "poll":
                appealManager.set_user_state(user_id, AppealStates.WAITING_VOTE_CONFIRM, data)
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("Да", callback_data=f"vote_yes_{new_case_id}"), types.InlineKeyboardButton("Нет", callback_data=f"vote_no_{new_case_id}"))
                bot.send_message(message.chat.id, "Вы принимали участие в этом голосовании?", reply_markup=markup)
            else:
                appealManager.set_user_state(user_id, AppealStates.WAITING_MAIN_ARGUMENT, data)
                bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")

        elif state == AppealStates.WAITING_MAIN_ARGUMENT:
            appealManager.update_appeal(data["case_id"], "applicant_arguments", message.text)
            appealManager.set_user_state(user_id, AppealStates.WAITING_Q1, data)
            bot.send_message(message.chat.id, "Вопрос 1/3: Какой пункт устава, по вашему мнению, был нарушен?")

        elif state == AppealStates.WAITING_Q1:
            _update_appeal_answer(data["case_id"], "q1", message.text)
            appealManager.set_user_state(user_id, AppealStates.WAITING_Q2, data)
            bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")

        elif state == AppealStates.WAITING_Q2:
            _update_appeal_answer(data["case_id"], "q2", message.text)
            appealManager.set_user_state(user_id, AppealStates.WAITING_Q3, data)
            bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")

        elif state == AppealStates.WAITING_Q3:
            _update_appeal_answer(data["case_id"], "q3", message.text)
            appealManager.delete_user_state(user_id)
            bot.send_message(message.chat.id, "Спасибо, ваша апелляция полностью оформлена.")
            request_counter_arguments(bot, data["case_id"])

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

        appeal = appealManager.get_appeal(case_id)
        if not appeal:
            bot.answer_callback_query(call.id, f"Критическая ошибка: дело #{case_id} не найдено в базе данных.", show_alert=True)
            appealManager.delete_user_state(user_id)
            return

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

        if action == "vote_yes":
            total_voters = appeal.get("total_voters")
            expected_responses = total_voters - 1 if total_voters is not None and total_voters > 0 else 0
            appealManager.update_appeal(case_id, "expected_responses", expected_responses)
            bot.send_message(call.message.chat.id, "Понятно. Ваш голос будет вычтен для объективности.")
        elif action == "vote_no":
            appealManager.update_appeal(case_id, "expected_responses", appeal.get("total_voters", 0))
            bot.send_message(call.message.chat.id, "Понятно. Информация принята.")

        appealManager.set_user_state(user_id, AppealStates.WAITING_MAIN_ARGUMENT, data)
        bot.send_message(call.message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")
        bot.answer_callback_query(call.id)

def _update_appeal_answer(case_id, key, value):
    appeal = appealManager.get_appeal(case_id)
    if appeal:
        current_answers = appeal.get("applicant_answers", {}) or {}
        current_answers[key] = value
        appealManager.update_appeal(case_id, "applicant_answers", current_answers)