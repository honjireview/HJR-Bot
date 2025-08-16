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

user_states = {}

# --- ИЗМЕНЕНИЕ: Выносим finalize_appeal на уровень модуля ---
def finalize_appeal(case_id, bot):
    appeal = appealManager.get_appeal(case_id)
    if not appeal or appeal.get('status') == 'closed':
        return

    print(f"Завершаю рассмотрение дела #{case_id}.")
    appealManager.update_appeal(case_id, 'status', 'closed')

    try:
        bot.send_message(appeal['applicant_chat_id'], f"Сбор контраргументов по делу #{case_id} завершен. Дело передано ИИ-арбитру.")
        bot.send_message(EDITORS_CHANNEL_ID, f"Сбор контраргументов по делу #{case_id} завершен. Дело передано ИИ-арбитру.")
    except Exception as e:
        print(f"Не удалось уведомить участников о завершении сбора: {e}")

    ai_verdict = geminiProcessor.get_verdict_from_gemini(case_id)

    # ИЗМЕНЕНИЕ: Сохраняем вердикт в БД
    appealManager.update_appeal(case_id, 'ai_verdict', ai_verdict)

    # ... (формирование final_report_text как раньше) ...
    final_report_text = f"⚖️ **Рассмотрение апелляции №{case_id}** ⚖️\n\n..." # Опущено для краткости

    try:
        bot.send_message(APPEALS_CHANNEL_ID, final_report_text, parse_mode="Markdown")
        bot.send_message(appeal['applicant_chat_id'], "Ваша апелляция рассмотрена. Результат ниже:")
        bot.send_message(appeal['applicant_chat_id'], final_report_text, parse_mode="Markdown")
        print(f"Отчет по делу #{case_id} успешно отправлен.")
    except Exception as e:
        print(f"Ошибка при отправке отчета по делу #{case_id}: {e}")

    # Теперь можно безопасно удалить
    # appealManager.delete_appeal(case_id) # Пока закомментируем, чтобы был архив

def register_handlers(bot):
    """Регистрирует все обработчики сообщений для бота."""

    @bot.message_handler(commands=['cancel'])
    def cancel_process(message):
        user_id = message.from_user.id
        state = user_states.pop(user_id, None)
        if state and 'case_id' in state:
            appealManager.delete_appeal(state['case_id'])
            bot.send_message(message.chat.id, "Процесс отменен. Все данные по этому делу удалены.", reply_markup=types.ReplyKeyboardRemove())
        else:
            bot.send_message(message.chat.id, "Нет активного процесса для отмены.", reply_markup=types.ReplyKeyboardRemove())

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
            bot.answer_callback_query(call.id, "Вы ничего не отправили.", show_alert=True)
            return

        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # ИЗМЕНЕНИЕ: Сразу меняем состояние
        user_states[user_id]['state'] = 'processing_items'
        process_collected_items(call.message)

    def process_collected_items(message):
        user_id = message.chat.id
        state_data = user_states.get(user_id)
        if not state_data: return

        full_decision_text, all_voters_to_mention, total_voters = "", [], None

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

        if total_voters is not None:
            user_states[user_id]['state'] = 'awaiting_vote_response'
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            msg = bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_applicant_voted_response, case_id)
        else:
            user_states[user_id]['state'] = 'awaiting_main_argument'
            msg = bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")
            bot.register_next_step_handler(msg, get_applicant_arguments, case_id)

    # ... (Остальная логика с вопросами и ответами остается почти такой же, но с правильным сохранением данных)
    # Например, в ask_applicant_question_2:
    def ask_applicant_question_2(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            # ИЗМЕНЕНИЕ: Правильно сохраняем данные
            current_answers = appeal.get('applicant_answers', {})
            current_answers['q1'] = message.text
            appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
        # ... (дальше по цепочке)