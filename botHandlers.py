# -*- coding: utf-8 -*-

import telebot
from telebot import types
import random
import os
import pandas as pd
import io
from datetime import datetime, timedelta

import appealManager
import geminiProcessor

EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')
APPEALS_CHANNEL_ID = os.getenv('APPEALS_CHANNEL_ID')

# Словарь для отслеживания состояния пользователей (user_id -> {'state': '...', 'case_id': ...})
user_states = {}

def register_handlers(bot):
    """Регистрирует все обработчики сообщений для бота."""

    # --- Команда отмены ---
    @bot.message_handler(commands=['cancel'])
    def cancel_process(message):
        user_id = message.from_user.id
        state = user_states.pop(user_id, None)
        if state and 'case_id' in state:
            appealManager.delete_appeal(state['case_id'])
            bot.send_message(message.chat.id, "Процесс отменен. Все данные по этому делу удалены.", reply_markup=types.ReplyKeyboardRemove())
        else:
            bot.send_message(message.chat.id, "Нет активного процесса для отмены.", reply_markup=types.ReplyKeyboardRemove())

    # --- Шаг 1: Начало ---
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_states.pop(message.from_user.id, None)
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(message.chat.id, "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс.", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        user_states[user_id] = {'state': 'collecting_items', 'items': []}
        markup = types.InlineKeyboardMarkup()
        done_button = types.InlineKeyboardButton("Готово, я все отправил(а)", callback_data="done_collecting")
        markup.add(done_button)
        bot.send_message(call.message.chat.id, "Пожалуйста, **перешлите** сюда все сообщения, опросы или CSV-файлы, которые вы хотите оспорить. Когда закончите, нажмите 'Готово'.\n\nДля отмены в любой момент введите /cancel", reply_markup=markup)

    # --- Шаг 2: Сбор предметов спора ---
    @bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('state') == 'collecting_items', content_types=['text', 'poll', 'document'])
    def handle_collecting_items(message):
        user_id = message.from_user.id
        is_forwarded = message.forward_from or message.forward_from_chat
        is_document = message.content_type == 'document'

        if not is_forwarded and not is_document:
            bot.send_message(message.chat.id, "Ошибка: Сообщение не было переслано. Пожалуйста, **перешлите** оригинальное сообщение.")
            return

        user_states[user_id]['items'].append(message)
        bot.send_message(message.chat.id, f"Принято ({len(user_states[user_id]['items'])}). Перешлите еще или нажмите 'Готово'.")

    @bot.callback_query_handler(func=lambda call: call.data == "done_collecting")
    def handle_done_collecting_callback(call):
        user_id = call.from_user.id
        state_data = user_states.get(user_id)

        if not state_data or not state_data.get('items'):
            bot.answer_callback_query(call.id, "Вы ничего не отправили. Пожалуйста, перешлите хотя бы одно сообщение.", show_alert=True)
            return

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        process_collected_items(call.message)

    def process_collected_items(message):
        user_id = message.chat.id
        state_data = user_states.get(user_id)
        if not state_data: return

        full_decision_text = ""
        all_voters_to_mention = []
        total_voters = None

        for item in state_data['items']:
            # ... (логика обработки text, poll, csv как раньше) ...
            pass # Опущено для краткости

        case_id = random.randint(10000, 99999)
        user_states[user_id]['case_id'] = case_id

        initial_data = {
            'applicant_chat_id': message.chat.id, 'decision_text': full_decision_text.strip(),
            'voters_to_mention': list(set(all_voters_to_mention)), 'applicant_answers': {},
            'council_answers': [], 'total_voters': total_voters, 'status': 'collecting'
        }
        appealManager.create_appeal(case_id, initial_data)
        bot.send_message(message.chat.id, f"Все объекты приняты. Вашему делу присвоен номер #{case_id}.")

        # ... (дальнейшая логика с вопросами заявителю) ...

    # --- Шаг 5: Сбор контраргументов ---
    @bot.message_handler(commands=['reply']) # ИЗМЕНЕНО: /reply
    def handle_counter_argument_command(message):
        # ... (логика как раньше, но с user_states для отмены) ...
        pass

# --- Глобальная функция для финальной стадии ---
def finalize_appeal(case_id, bot):
    appeal = appealManager.get_appeal(case_id)
    if not appeal or appeal.get('status') == 'closed':
        return

    print(f"Завершаю рассмотрение дела #{case_id}.")
    appealManager.update_appeal(case_id, 'status', 'closed')

    ai_verdict = geminiProcessor.get_verdict_from_gemini(case_id)

    # ... (формирование и отправка отчета) ...

    # appealManager.delete_appeal(case_id) # ЗАКОММЕНТИРОВАНО: не удаляем дело