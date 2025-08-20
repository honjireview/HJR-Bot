# -*- coding: utf-8 -*-

import telebot
from telebot import types
import random
import os
import pandas as pd
import io
import logging
from datetime import datetime, timedelta

import appealManager
from .council_flow import finalize_appeal

EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')
log = logging.getLogger("hjr-bot")

def register_applicant_handlers(bot, user_states):
    """
    Регистрирует обработчики для процесса подачи апелляции.
    """

    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_states.pop(message.from_user.id, None)
        log.info(f"[dialog] /start user={message.from_user.id}")
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(message.chat.id, "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс.", reply_markup=markup)

    @bot.message_handler(commands=['cancel'])
    def cancel_process(message):
        user_id = message.from_user.id
        state = user_states.pop(user_id, None)
        if state and 'case_id' in state:
            appealManager.delete_appeal(state['case_id'])
        bot.send_message(message.chat.id, "Процесс подачи апелляции отменен.", reply_markup=types.ReplyKeyboardRemove())

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        user_states[user_id] = {'state': 'collecting_items', 'items': []}
        log.info(f"[dialog] start_appeal user={user_id} state=collecting_items")
        markup = types.InlineKeyboardMarkup()
        done_button = types.InlineKeyboardButton("Готово, я все отправил(а)", callback_data="done_collecting")
        markup.add(done_button)
        bot.send_message(call.message.chat.id, "Пожалуйста, **перешлите** сюда все сообщения, опросы или CSV-файлы, которые вы хотите оспорить. Когда закончите, нажмите 'Готово'.\n\nДля отмены в любой момент введите /cancel", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "done_collecting")
    def handle_done_collecting_callback(call):
        user_id = call.from_user.id
        state_data = user_states.get(user_id)
        if not state_data or not state_data.get('items'):
            bot.answer_callback_query(call.id, "Вы ничего не отправили.", show_alert=True)
            return
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        process_collected_items(bot, user_id, call.message, user_states)

    def process_collected_items(bot, user_id, message, user_states):
        state_data = user_states.get(user_id)
        if not state_data: return

        full_decision_text, poll_count, total_voters = "", 0, None
        for item in state_data['items']:
            if item.content_type == 'poll':
                poll_count += 1
                poll = item.poll
                total_voters = poll.total_voter_count
                options_text = "\n".join([f"- {opt.text}: {opt.voter_count} голосов" for opt in poll.options])
                full_decision_text += f"\n\n--- Опрос ---\nВопрос: {poll.question}\n{options_text}"
            elif item.content_type == 'text':
                full_decision_text += f"\n\n--- Сообщение ---\n{item.text}"

        if poll_count > 1:
            bot.send_message(message.chat.id, "Ошибка: Вы можете оспорить только одно голосование за раз. Начните заново: /start")
            user_states.pop(user_id, None)
            return

        case_id = random.randint(10000, 99999)
        user_states[user_id]['case_id'] = case_id
        initial_data = {'applicant_chat_id': message.chat.id, 'decision_text': full_decision_text.strip(), 'total_voters': total_voters, 'status': 'collecting'}
        appealManager.create_appeal(case_id, initial_data)
        bot.send_message(message.chat.id, f"Все объекты приняты. Вашему делу присвоен номер #{case_id}.")

        if poll_count == 1:
            user_states[user_id]['state'] = 'awaiting_vote_response'
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
        else:
            user_states[user_id]['state'] = 'awaiting_main_argument'
            bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")

    def request_counter_arguments(bot, case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return

        request_text = f"📣 **Запрос контраргументов по апелляции №{case_id}** 📣\n\n..." # Текст как раньше
        bot.send_message(EDITORS_CHANNEL_ID, request_text, parse_mode="Markdown")

        expires_at = datetime.utcnow() + timedelta(hours=24)
        appealManager.update_appeal(case_id, 'timer_expires_at', expires_at)
        log.info(f"Таймер для дела #{case_id} установлен на {expires_at.isoformat()}")

    # ИСПРАВЛЕНО: Обработчик теперь реагирует только на состояния, связанные с апелляцией
    @bot.message_handler(
        func=lambda message: str(user_states.get(message.from_user.id, {}).get('state', '')).startswith('awaiting_') or user_states.get(message.from_user.id, {}).get('state') == 'collecting_items',
        content_types=['text', 'poll', 'document']
    )
    def handle_dialogue_messages(message):
        user_id = message.from_user.id
        state_data = user_states.get(user_id)
        if not state_data: return

        state = state_data.get('state')
        case_id = state_data.get('case_id')

        if state == 'collecting_items':
            # ИСПРАВЛЕНО: Принимаем только пересланные сообщения
            if not message.forward_from and not message.forward_from_chat:
                bot.send_message(message.chat.id, "Ошибка: Сообщение не было переслано. Пожалуйста, **перешлите** оригинальное сообщение.")
                return

            state_data['items'].append(message)
            log.info(f"[collect] accepted forwarded message, items={len(state_data['items'])}")
            bot.send_message(message.chat.id, f"Принято ({len(state_data['items'])}). Перешлите еще или нажмите 'Готово'.")
            return

        elif state == 'awaiting_vote_response':
            appeal = appealManager.get_appeal(case_id)
            if not appeal: return
            if message.text.startswith("Да"):
                expected_responses = (appeal.get('total_voters') or 1) - 1
                appealManager.update_appeal(case_id, 'expected_responses', expected_responses)
                user_states[user_id]['state'] = 'awaiting_main_argument'
                bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            elif message.text.startswith("Нет"):
                bot.send_message(message.chat.id, "Согласно правилам, все участники должны принимать участие в голосовании. Ваша заявка отклонена.", reply_markup=types.ReplyKeyboardRemove())
                appealManager.delete_appeal(case_id)
                user_states.pop(user_id, None)
            else:
                bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа.")

        elif state == 'awaiting_main_argument':
            appealManager.update_appeal(case_id, 'applicant_arguments', message.text)
            user_states[user_id]['state'] = 'awaiting_q1'
            bot.send_message(message.chat.id, "Спасибо. Теперь ответьте на уточняющие вопросы.")
            bot.send_message(message.chat.id, "Вопрос 1/3: Какой пункт устава, по вашему мнению, был нарушен?")

        elif state == 'awaiting_q1':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q1'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states[user_id]['state'] = 'awaiting_q2'
            bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")

        elif state == 'awaiting_q2':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q2'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states[user_id]['state'] = 'awaiting_q3'
            bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")

        elif state == 'awaiting_q3':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q3'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states.pop(user_id, None)
            log.info(f"[flow] q3 saved; dialog closed case_id={case_id}")
            request_counter_arguments(bot, case_id)