# app/handlers/appeal.py
# -*- coding: utf-8 -*-
import logging
import random
from datetime import datetime
from telebot import types

from app.services import appeal_service, editor_service
from app.repositories import state_repo, appeal_repo
from utils.telegram_helpers import validate_appeal_link
from utils.council_helpers import request_counter_arguments

log = logging.getLogger("hjr-bot.handlers.appeal")

APPLICANT_STATE_PREFIX = "applicant_"
class AppealStates:
    WAITING_FOR_LINK = f"{APPLICANT_STATE_PREFIX}waiting_for_link"
    WAITING_VOTE_CONFIRM = f"{APPLICANT_STATE_PREFIX}waiting_vote_confirm"
    WAITING_MAIN_ARGUMENT = f"{APPLICANT_STATE_PREFIX}waiting_main_argument"
    WAITING_Q1 = f"{APPLICANT_STATE_PREFIX}waiting_q1"
    WAITING_Q2 = f"{APPLICANT_STATE_PREFIX}waiting_q2"
    WAITING_Q3 = f"{APPLICANT_STATE_PREFIX}waiting_q3"

def _render_item_text(item: dict) -> str:
    # ... (код без изменений из applicant_flow.py)
    pass

def register_appeal_handlers(bot):
    @bot.message_handler(commands=["start"], chat_types=['private'])
    def send_welcome(message):
        user_id = message.from_user.id
        if not editor_service.is_user_an_editor(bot, user_id):
            bot.send_message(message.chat.id, "Эта функция доступна только для участников Совета Редакторов.")
            return

        if state_repo.get(user_id) is not None:
            bot.send_message(message.chat.id, "Вы уже находитесь в процессе. Чтобы начать заново, отмените его: /cancel.")
            return

        state_repo.delete(user_id)
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(message.chat.id, "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс.", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        if not editor_service.is_user_an_editor(bot, user_id):
            bot.answer_callback_query(call.id, "Эта функция доступна только для участников Совета Редакторов.", show_alert=True)
            return

        if appeal_repo.get_active_appeal_by_user(user_id):
            bot.answer_callback_query(call.id, "У вас уже есть активная апелляция.", show_alert=True)
            return

        state_repo.set(user_id, AppealStates.WAITING_FOR_LINK)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Пожалуйста, пришлите ссылку на решение, которое вы хотите оспорить.")

    # ... и так далее для всех остальных обработчиков из applicant_flow, council_flow и review_flow,
    # заменяя вызовы appealManager на вызовы соответствующих репозиториев и сервисов.