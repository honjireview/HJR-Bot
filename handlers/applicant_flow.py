# -*- coding: utf-8 -*-

import telebot
from telebot import types
import random
import os
import pandas as pd
import io
from datetime import datetime, timedelta

import appealManager
from .council_flow import finalize_appeal

EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')

def register_applicant_handlers(bot, user_states):
    """
    Регистрирует обработчики для процесса подачи апелляции.
    """

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
            return # Просто игнорируем обычные сообщения на этом этапе

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
        process_collected_items(bot, call.message, user_states)

    def process_collected_items(bot, message, user_states):
        user_id = message.chat.id
        state_data = user_states.get(user_id)
        if not state_data: return

        full_decision_text, all_voters_to_mention, total_voters, poll_count = "", [], None, 0
        for item in state_data['items']:
            if item.content_type == 'poll':
                poll_count += 1
                poll = item.poll
                total_voters = poll.total_voter_count
                options_text = "\n".join([f"- {opt.text}: {opt.voter_count} голосов" for opt in poll.options])
                full_decision_text += f"\n\n--- Опрос ---\nВопрос: {poll.question}\n{options_text}"
            elif item.content_type == 'text':
                full_decision_text += f"\n\n--- Сообщение ---\n{item.text}"
            elif item.content_type == 'document' and item.document.mime_type == 'text/csv':
                try:
                    file_info = bot.get_file(item.document.file_id)
                    downloaded_file = bot.download_file(file_info.file_path)
                    df = pd.read_csv(io.BytesIO(downloaded_file))
                    full_decision_text += "\n\n--- Данные из Google Forms (CSV) ---\n" + df.to_markdown(index=False)
                    mention_col = 'Username' if 'Username' in df.columns else 'UserID' if 'UserID' in df.columns else None
                    if mention_col: all_voters_to_mention.extend(df[mention_col].dropna().tolist())
                except Exception as e:
                    bot.send_message(message.chat.id, f"Ошибка обработки CSV: {e}. Этот файл будет проигнорирован.")

        if poll_count > 1:
            bot.send_message(message.chat.id, "Ошибка: Вы можете оспорить только одно голосование за раз. Начните заново: /start")
            user_states.pop(user_id, None)
            return

        case_id = random.randint(10000, 99999)
        user_states[user_id]['case_id'] = case_id
        initial_data = {
            'applicant_chat_id': message.chat.id, 'decision_text': full_decision_text.strip(),
            'voters_to_mention': list(set(all_voters_to_mention)), 'total_voters': total_voters, 'status': 'collecting'
        }
        appealManager.create_appeal(case_id, initial_data)
        bot.send_message(message.chat.id, f"Все объекты приняты. Вашему делу присвоен номер #{case_id}.")

        if poll_count == 1:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            msg = bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_applicant_voted_response, bot, user_states, case_id)
        else:
            msg = bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")
            bot.register_next_step_handler(msg, get_applicant_arguments, bot, user_states, case_id)

    # --- Шаг 3: Цепочка вопросов заявителю (с использованием register_next_step_handler) ---
    def handle_applicant_voted_response(message, bot, user_states, case_id):
        user_id = message.from_user.id
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return

        if message.text.startswith("Да"):
            expected_responses = (appeal.get('total_voters') or 1) - 1
            appealManager.update_appeal(case_id, 'expected_responses', expected_responses)
            msg = bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            bot.register_next_step_handler(msg, get_applicant_arguments, bot, user_states, case_id)
        elif message.text.startswith("Нет"):
            bot.send_message(message.chat.id, "Согласно правилам, все участники должны принимать участие в голосовании. Ваша заявка отклонена.", reply_markup=types.ReplyKeyboardRemove())
            appealManager.delete_appeal(case_id)
            user_states.pop(user_id, None)
        else:
            bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа.")
            bot.register_next_step_handler(message, handle_applicant_voted_response, bot, user_states, case_id)

    def get_applicant_arguments(message, bot, user_states, case_id):
        appealManager.update_appeal(case_id, 'applicant_arguments', message.text)
        bot.send_message(message.chat.id, "Спасибо. Теперь ответьте, пожалуйста, на несколько уточняющих вопросов.")
        msg = bot.send_message(message.chat.id, "Вопрос 1/3: Какой конкретно пункт устава, по вашему мнению, был нарушен?")
        bot.register_next_step_handler(msg, ask_applicant_question_2, bot, user_states, case_id)

    def ask_applicant_question_2(message, bot, user_states, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            current_answers = appeal.get('applicant_answers', {}) or {}
            current_answers['q1'] = message.text
            appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
        msg = bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")
        bot.register_next_step_handler(msg, ask_applicant_question_3, bot, user_states, case_id)

    def ask_applicant_question_3(message, bot, user_states, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            current_answers = appeal.get('applicant_answers', {}) or {}
            current_answers['q2'] = message.text
            appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
        msg = bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")
        bot.register_next_step_handler(msg, request_counter_arguments, bot, user_states, case_id)

    def request_counter_arguments(message, bot, user_states, case_id):
        user_id = message.from_user.id
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return

        current_answers = appeal.get('applicant_answers', {}) or {}
        current_answers['q3'] = message.text
        appealManager.update_appeal(case_id, 'applicant_answers', current_answers)

        user_states.pop(user_id, None) # Завершаем диалог с заявителем

        bot.send_message(message.chat.id, "Спасибо! Ваша заявка полностью сформирована и передана в Совет Редакторов. У Совета есть 24 часа на предоставление контраргументов.")

        request_text = f"""
📣 **Запрос контраргументов по апелляции №{case_id}** 📣

**Заявитель оспаривает решение:**
`{appeal['decision_text']}`

**Аргументы заявителя:**
`{appeal.get('applicant_arguments', '')}`
"""
        if appeal.get('voters_to_mention'):
            mentions = " ".join([f"@{str(v).replace('@', '')}" for v in appeal['voters_to_mention']])
            request_text += f"\n\nПрошу следующих участников: {mentions} предоставить свои контраргументы."
        else:
            request_text += f"\n\nПрошу Совет предоставить свою позицию по данному решению."
        request_text += f"\n\nУ вас есть 24 часа. Для ответа используйте команду `/reply {case_id}` в личном чате с ботом."
        bot.send_message(EDITORS_CHANNEL_ID, request_text, parse_mode="Markdown")

        expires_at = datetime.utcnow() + timedelta(hours=24)
        appealManager.update_appeal(case_id, 'timer_expires_at', expires_at)
        print(f"Таймер для дела #{case_id} установлен на {expires_at.isoformat()}")