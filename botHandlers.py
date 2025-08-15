# -*- coding: utf-8 -*-

import telebot
from telebot import types
import random
import config
import os
import pandas as pd
import io
import threading

# Импортируем наши модули
import appealManager
import geminiProcessor

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

        decision_text = ""
        voters_to_mention = []
        total_voters = None # <-- Для хранения кол-ва проголосовавших

        if message.content_type == 'text':
            decision_text = message.text
        elif message.content_type == 'poll':
            poll = message.poll
            total_voters = poll.total_voter_count # <-- Считываем кол-во проголосовавших
            options_text = "\n".join([f"- {opt.text}: {opt.voter_count} голосов" for opt in poll.options])
            decision_text = f"Результаты голосования:\nВопрос: {poll.question}\n---\n{options_text}"
        elif is_document and message.document.mime_type == 'text/csv':
            try:
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                df = pd.read_csv(io.BytesIO(downloaded_file))
                decision_text = "Данные из Google Forms (CSV):\n---\n" + df.to_markdown(index=False)
                mention_col = 'Username' if 'Username' in df.columns else 'UserID' if 'UserID' in df.columns else None
                if mention_col:
                    voters_to_mention = df[mention_col].dropna().tolist()
            except Exception as e:
                bot.send_message(message.chat.id, f"Не удалось обработать CSV-файл. Ошибка: {e}. Начните заново: /start")
                return
        else:
            bot.send_message(message.chat.id, "Неверный формат. Пожалуйста, перешлите текстовое сообщение, опрос или пришлите CSV-файл. Начните заново: /start")
            return

        case_id = random.randint(1000, 9999)
        initial_data = {
            'applicant_chat_id': message.chat.id,
            'decision_text': decision_text,
            'voters_to_mention': voters_to_mention,
            'applicant_answers': {},
            'council_answers': [],
            'total_voters': total_voters, # <-- Сохраняем кол-во
            'status': 'collecting' # <-- Статус дела
        }
        appealManager.create_appeal(case_id, initial_data)

        bot.send_message(message.chat.id, f"Принято. Вашему делу присвоен номер #{case_id}.")

        if total_voters is not None:
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            msg = bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_applicant_voted_response, case_id)
        else:
            msg = bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы, почему это решение следует пересмотреть.")
            bot.register_next_step_handler(msg, get_applicant_arguments, case_id)

    def handle_applicant_voted_response(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return

        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        if message.text.startswith("Да"):
            expected_responses = appeal['total_voters'] - 1
            appealManager.update_appeal(case_id, 'expected_responses', expected_responses)
            msg = bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            bot.register_next_step_handler(msg, get_applicant_arguments, case_id)
        elif message.text.startswith("Нет"):
            bot.send_message(message.chat.id, "Согласно правилам (п. 7.7 Устава), все участники должны принимать участие в голосовании. Ваша заявка отклонена, так как вы не голосовали.", reply_markup=types.ReplyKeyboardRemove())
            appealManager.delete_appeal(case_id) # Удаляем дело
        else:
            # Если пользователь написал что-то другое
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            msg = bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа: 'Да' или 'Нет'.", reply_markup=markup)
            bot.register_next_step_handler(msg, handle_applicant_voted_response, case_id)


    # --- Шаг 3: Сбор аргументов и доп. вопросов ЗАЯВИТЕЛЮ ---
    def get_applicant_arguments(message, case_id):
        appealManager.update_appeal(case_id, 'applicant_arguments', message.text)
        bot.send_message(message.chat.id, "Спасибо. Теперь ответьте, пожалуйста, на несколько уточняющих вопросов.")
        ask_applicant_question_1(message, case_id)

    def ask_applicant_question_1(message, case_id):
        msg = bot.send_message(message.chat.id, "Вопрос 1/3: Какой конкретно пункт устава, по вашему мнению, был нарушен этим решением?")
        bot.register_next_step_handler(msg, ask_applicant_question_2, case_id)

    def ask_applicant_question_2(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            appeal['applicant_answers']['q1'] = message.text
        msg = bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым в этой ситуации?")
        bot.register_next_step_handler(msg, ask_applicant_question_3, case_id)

    def ask_applicant_question_3(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if appeal:
            appeal['applicant_answers']['q2'] = message.text
        msg = bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли какие-либо дополнительные факты или контекст, которые, по вашему мнению, важны для рассмотрения дела?")
        bot.register_next_step_handler(msg, request_counter_arguments, case_id)

    # --- Шаг 4: Запрос контраргументов у Совета и ЗАПУСК ТАЙМЕРА ---
    def request_counter_arguments(message, case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal: return
        appeal['applicant_answers']['q3'] = message.text
        bot.send_message(message.chat.id, "Спасибо! Ваша заявка полностью сформирована и передана в Совет Редакторов. У Совета есть 24 часа на предоставление контраргументов.")

        request_text = f"""
📣 **Запрос контраргументов по апелляции №{case_id}** 📣

**Заявитель оспаривает решение:**
`{appeal['decision_text']}`

**Аргументы заявителя:**
`{appeal['applicant_arguments']}`
"""
        if appeal['voters_to_mention']:
            mentions = " ".join([f"@{str(v).replace('@', '')}" for v in appeal['voters_to_mention']])
            request_text += f"\n\nПрошу следующих участников: {mentions} предоставить свои контраргументы."
        else:
            request_text += f"\n\nПрошу Совет предоставить свою позицию по данному решению."
        request_text += f"\n\nУ вас есть 24 часа. Для ответа используйте команду `/ответ {case_id}` в личном чате с ботом."
        bot.send_message(config.EDITORS_CHANNEL_ID, request_text, parse_mode="Markdown")

        print(f"Запускаю 24-часовой таймер для дела #{case_id}...")
        timer = threading.Timer(86400, finalize_appeal_after_timeout, [case_id])
        appealManager.update_appeal(case_id, 'timer', timer) # Сохраняем таймер
        timer.start()

    # --- Шаг 5: Сбор контраргументов и доп. вопросов СОВЕТУ ---
    @bot.message_handler(commands=['ответ'])
    def handle_counter_argument_command(message):
        try:
            parts = message.text.split()
            case_id = int(parts[1])
            if not appealManager.get_appeal(case_id):
                bot.send_message(message.chat.id, f"Дело с номером {case_id} не найдено или уже закрыто.")
                return

            user_id = message.from_user.id
            if any(answer['user_id'] == user_id for answer in appealManager.get_appeal(case_id)['council_answers']):
                bot.send_message(message.chat.id, "Вы уже предоставили ответ по этому делу.")
                return

            msg = bot.send_message(message.chat.id, f"Изложите, пожалуйста, основные контраргументы Совета по делу #{case_id}.")
            bot.register_next_step_handler(msg, ask_council_question_1, case_id, message.from_user)
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "Неверный формат. Используйте: /ответ [номер_дела]")

    def ask_council_question_1(message, case_id, user):
        temp_answer = {
            'user_id': user.id,
            'responder_info': f"Ответ от {user.first_name} (@{user.username})",
            'main_arg': message.text
        }
        msg = bot.send_message(message.chat.id, "Вопрос 1/2: На каких пунктах устава или предыдущих решениях основывалась позиция Совета?")
        bot.register_next_step_handler(msg, ask_council_question_2, case_id, temp_answer)

    def ask_council_question_2(message, case_id, temp_answer):
        temp_answer['q1'] = message.text
        msg = bot.send_message(message.chat.id, "Вопрос 2/2: Какие аргументы заявителя вы считаете несостоятельными и почему?")
        bot.register_next_step_handler(msg, save_council_answers, case_id, temp_answer)

    def save_council_answers(message, case_id, temp_answer):
        temp_answer['q2'] = message.text
        appealManager.add_council_answer(case_id, temp_answer)
        bot.send_message(message.chat.id, f"Ваш ответ по делу #{case_id} принят и будет учтен при вынесении вердикта. Спасибо!")

        # --- НОВАЯ ПРОВЕРКА: ЗАВЕРШАЕМ ДОСРОЧНО? ---
        appeal = appealManager.get_appeal(case_id)
        if appeal and appeal.get('expected_responses') is not None:
            if len(appeal['council_answers']) >= appeal['expected_responses']:
                print(f"Все {appeal['expected_responses']} ответов по делу #{case_id} собраны. Завершаю досрочно.")
                # Отменяем таймер, чтобы он не сработал второй раз
                if 'timer' in appeal and appeal['timer']:
                    appeal['timer'].cancel()
                # Запускаем финальный этап
                finalize_appeal_after_timeout(case_id)


    # --- Шаг 6: Финальное рассмотрение (срабатывает по таймеру или досрочно) ---
    def finalize_appeal_after_timeout(case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal or appeal.get('status') == 'closed':
            return # Если дела нет или оно уже закрыто, ничего не делаем

        print(f"Завершаю рассмотрение дела #{case_id}.")
        appealManager.update_appeal(case_id, 'status', 'closed') # Меняем статус

        bot.send_message(appeal['applicant_chat_id'], f"Сбор контраргументов по делу #{case_id} завершен. Дело передано на рассмотрение ИИ-арбитру.")
        bot.send_message(config.EDITORS_CHANNEL_ID, f"Сбор контраргументов по делу #{case_id} завершен. Дело передано на рассмотрение ИИ-арбитру.")

        ai_verdict = geminiProcessor.get_verdict_from_gemini(case_id)

        applicant_full_text = f"""
Основные аргументы: {appeal.get('applicant_arguments', 'не указано')}
Ответ на вопрос о нарушении устава: {appeal['applicant_answers'].get('q1', 'не указано')}
Ответ на вопрос о справедливом решении: {appeal['applicant_answers'].get('q2', 'не указано')}
Дополнительный контекст: {appeal['applicant_answers'].get('q3', 'не указано')}
"""
        council_answers_list = appeal.get('council_answers', [])
        if council_answers_list:
            council_full_text = ""
            for answer in council_answers_list:
                council_full_text += f"""
---
{answer.get('responder_info', 'Ответ от Совета')}:
Основные контраргументы: {answer.get('main_arg', 'не указано')}
Основание (пункты устава): {answer.get('q1', 'не указано')}
Оценка аргументов заявителя: {answer.get('q2', 'не указано')}
---
"""
        else:
            council_full_text = "Совет не предоставил контраргументов в установленный срок."

        final_report_text = f"""
⚖️ **Рассмотрение апелляции №{case_id}** ⚖️

**Оспариваемое решение (данные):**
`{appeal['decision_text']}`

**Позиция заявителя:**
`{applicant_full_text}`

**Позиция Совета:**
`{council_full_text}`

---

**{ai_verdict}**
"""

        try:
            bot.send_message(config.APPEALS_CHANNEL_ID, final_report_text, parse_mode="Markdown")
            bot.send_message(appeal['applicant_chat_id'], "Ваша апелляция рассмотрена. Результат ниже:")
            bot.send_message(appeal['applicant_chat_id'], final_report_text, parse_mode="Markdown")
            print(f"Отчет по делу #{case_id} успешно отправлен.")
        except Exception as e:
            print(f"Ошибка при отправке отчета по делу #{case_id}: {e}")

        appealManager.delete_appeal(case_id)