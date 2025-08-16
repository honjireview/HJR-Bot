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

# Получаем ID каналов из переменных окружения
EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')
APPEALS_CHANNEL_ID = os.getenv('APPEALS_CHANNEL_ID')

def register_handlers(bot):
    """
    Регистрирует все обработчики сообщений и колбэков для бота.
    """

    # --- Шаг 1: Начало ---
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        welcome_text = "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс."
        bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        msg = bot.send_message(call.message.chat.id, "Пожалуйста, **перешлите** сюда сообщение, опрос (голосование) ИЛИ **пришлите CSV-файл** с результатами из Google Forms, который вы хотите оспорить.")
        bot.register_next_step_handler(call.message, handle_decision_input)

    # --- Шаг 2: Прием предмета спора ---
    def handle_decision_input(message):
        is_forwarded = message.forward_from or message.forward_from_chat
        is_document = message.content_type == 'document'

        if not is_forwarded and not is_document:
            bot.send_message(message.chat.id, "Ошибка: Сообщение не было переслано, и это не документ. Начните заново: /start")
            return

        decision_text, voters_to_mention, total_voters = "", [], None

        if message.content_type == 'text':
            decision_text = message.text
        elif message.content_type == 'poll':
            poll = message.poll
            total_voters = poll.total_voter_count
            options_text = "\n".join([f"- {opt.text}: {opt.voter_count} голосов" for opt in poll.options])
            decision_text = f"Результаты голосования:\nВопрос: {poll.question}\n---\n{options_text}"
        elif is_document and message.document.mime_type == 'text/csv':
            try:
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                df = pd.read_csv(io.BytesIO(downloaded_file))
                decision_text = "Данные из Google Forms (CSV):\n---\n" + df.to_markdown(index=False)
                mention_col = 'Username' if 'Username' in df.columns else 'UserID' if 'UserID' in df.columns else None
                if mention_col: voters_to_mention = df[mention_col].dropna().tolist()
            except Exception as e:
                bot.send_message(message.chat.id, f"Не удалось обработать CSV-файл. Ошибка: {e}. Начните заново: /start")
                return
        else:
            bot.send_message(message.chat.id, "Неверный формат. Пожалуйста, перешлите текстовое сообщение, опрос или пришлите CSV-файл. Начните заново: /start")
            return

        case_id = random.randint(10000, 99999)
        initial_data = {
            'applicant_chat_id': message.chat.id, 'decision_text': decision_text,
            'voters_to_mention': voters_to_mention, 'applicant_answers': {},
            'council_answers': [], 'total_voters': total_voters, 'status': 'collecting'
        }
        appealManager.create_appeal(case_id, initial_data)
        bot.send_message(message.chat.id, f"Принято. Вашему делу присвоен номер #{case_id}.")

        if total_voters is not None:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            msg = bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_applicant_voted_response, case_id)
        else:
            msg = bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")
            bot.register_next_step_handler(msg, get_applicant_arguments, case_id)

    def handle_applicant_voted_response(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return

        if message.text.startswith("Да"):
            expected_responses = appeal['total_voters'] - 1
            appealManager.update_appeal(case_id, 'expected_responses', expected_responses)
            msg = bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            bot.register_next_step_handler(msg, get_applicant_arguments, case_id)
        elif message.text.startswith("Нет"):
            bot.send_message(message.chat.id, "Согласно правилам, все участники должны принимать участие в голосовании. Ваша заявка отклонена.", reply_markup=types.ReplyKeyboardRemove())
            appealManager.delete_appeal(case_id)
        else:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            msg = bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа.", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_applicant_voted_response, case_id)

    def get_applicant_arguments(message, case_id):
        appealManager.update_appeal(case_id, 'applicant_arguments', message.text)
        bot.send_message(message.chat.id, "Спасибо. Теперь ответьте, пожалуйста, на несколько уточняющих вопросов.")
        ask_applicant_question_1(message, case_id)

    def ask_applicant_question_1(message, case_id):
        msg = bot.send_message(message.chat.id, "Вопрос 1/3: Какой конкретно пункт устава, по вашему мнению, был нарушен?")
        bot.register_next_step_handler(msg, ask_applicant_question_2, case_id)

    def ask_applicant_question_2(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            appeal['applicant_answers']['q1'] = message.text
            appealManager.update_appeal(case_id, 'applicant_answers', appeal['applicant_answers'])
        msg = bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")
        bot.register_next_step_handler(msg, ask_applicant_question_3, case_id)

    def ask_applicant_question_3(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            appeal['applicant_answers']['q2'] = message.text
            appealManager.update_appeal(case_id, 'applicant_answers', appeal['applicant_answers'])
        msg = bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")
        bot.register_next_step_handler(msg, request_counter_arguments, case_id)

    def request_counter_arguments(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return
        appeal['applicant_answers']['q3'] = message.text
        appealManager.update_appeal(case_id, 'applicant_answers', appeal['applicant_answers'])

        bot.send_message(message.chat.id, "Спасибо! Ваша заявка полностью сформирована и передана в Совет Редакторов. У Совета есть 24 часа на предоставление контраргументов.")

        request_text = f"📣 **Запрос контраргументов по апелляции №{case_id}** 📣\n\n..." # (Текст как раньше)
        bot.send_message(EDITORS_CHANNEL_ID, request_text, parse_mode="Markdown")

        # Устанавливаем время истечения таймера в БД
        expires_at = datetime.utcnow() + timedelta(hours=24)
        appealManager.update_appeal(case_id, 'timer_expires_at', expires_at)
        print(f"Таймер для дела #{case_id} установлен на {expires_at.isoformat()}")

    @bot.message_handler(commands=['ответ'])
    def handle_counter_argument_command(message):
        try:
            parts = message.text.split()
            case_id = int(parts[1])
            if not appealManager.get_appeal(case_id):
                bot.send_message(message.chat.id, f"Дело с номером {case_id} не найдено или уже закрыто.")
                return

            user_id = message.from_user.id
            # Проверяем, не отвечал ли этот редактор уже
            current_answers = appealManager.get_appeal(case_id).get('council_answers', [])
            if any(answer['user_id'] == user_id for answer in current_answers):
                bot.send_message(message.chat.id, "Вы уже предоставили ответ по этому делу.")
                return

            msg = bot.send_message(message.chat.id, f"Изложите, пожалуйста, основные контраргументы Совета по делу #{case_id}.")
            bot.register_next_step_handler(msg, ask_council_question_1, case_id, message.from_user)
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "Неверный формат. Используйте: /ответ [номер_дела]")

    def ask_council_question_1(message, case_id, user):
        temp_answer = {
            'user_id': user.id, 'responder_info': f"Ответ от {user.first_name} (@{user.username})",
            'main_arg': message.text
        }
        msg = bot.send_message(message.chat.id, "Вопрос 1/2: На каких пунктах устава основывалась позиция Совета?")
        bot.register_next_step_handler(msg, ask_council_question_2, case_id, temp_answer)

    def ask_council_question_2(message, case_id, temp_answer):
        temp_answer['q1'] = message.text
        msg = bot.send_message(message.chat.id, "Вопрос 2/2: Какие аргументы заявителя вы считаете несостоятельными и почему?")
        bot.register_next_step_handler(msg, save_council_answers, case_id, temp_answer)

    def save_council_answers(message, case_id, temp_answer):
        temp_answer['q2'] = message.text
        appealManager.add_council_answer(case_id, temp_answer)
        bot.send_message(message.chat.id, f"Ваш ответ по делу #{case_id} принят. Спасибо!")

        appeal = appealManager.get_appeal(case_id)
        if appeal and appeal.get('expected_responses') is not None:
            if len(appeal.get('council_answers', [])) >= appeal['expected_responses']:
                print(f"Все ответы по делу #{case_id} собраны. Завершаю досрочно.")
                finalize_appeal(case_id, bot)

# --- Глобальная функция для финальной стадии ---
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

    # ... (формирование и отправка final_report_text как раньше) ...
    final_report_text = "..."

    try:
        bot.send_message(APPEALS_CHANNEL_ID, final_report_text, parse_mode="Markdown")
        bot.send_message(appeal['applicant_chat_id'], "Ваша апелляция рассмотрена. Результат ниже:")
        bot.send_message(appeal['applicant_chat_id'], final_report_text, parse_mode="Markdown")
        print(f"Отчет по делу #{case_id} успешно отправлен.")
    except Exception as e:
        print(f"Ошибка при отправке отчета по делу #{case_id}: {e}")

    appealManager.delete_appeal(case_id)