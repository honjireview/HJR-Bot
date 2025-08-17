# -*- coding: utf-8 -*-

import telebot
from telebot import types
import os
import appealManager
import geminiProcessor

EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')
APPEALS_CHANNEL_ID = os.getenv('APPEALS_CHANNEL_ID')

def finalize_appeal(case_id, bot):
    appeal = appealManager.get_appeal(case_id)
    if not appeal or appeal.get('status') == 'closed':
        return

    print(f"Завершаю рассмотрение дела #{case_id}.")
    appealManager.update_appeal(case_id, 'status', 'closed')

    ai_verdict = geminiProcessor.get_verdict_from_gemini(case_id)
    appealManager.update_appeal(case_id, 'ai_verdict', ai_verdict)

    applicant_full_text = f"""
Основные аргументы: {appeal.get('applicant_arguments', 'не указано')}
Ответ на вопрос о нарушении устава: {appeal.get('applicant_answers', {}).get('q1', 'не указано')}
Ответ на вопрос о справедливом решении: {appeal.get('applicant_answers', {}).get('q2', 'не указано')}
Дополнительный контекст: {appeal.get('applicant_answers', {}).get('q3', 'не указано')}
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
        bot.send_message(APPEALS_CHANNEL_ID, final_report_text, parse_mode="Markdown")
        bot.send_message(appeal['applicant_chat_id'], "Ваша апелляция рассмотрена. Результат ниже:")
        bot.send_message(appeal['applicant_chat_id'], final_report_text, parse_mode="Markdown")
        print(f"Отчет по делу #{case_id} успешно отправлен.")
    except Exception as e:
        print(f"Ошибка при отправке отчета по делу #{case_id}: {e}")

def register_council_handlers(bot, user_states):
    """
    Регистрирует обработчики для процесса ответа от Совета.
    """

    @bot.message_handler(commands=['reply'])
    def handle_reply_command(message):
        try:
            parts = message.text.split()
            case_id = int(parts[1])
            if not appealManager.get_appeal(case_id):
                bot.send_message(message.chat.id, f"Дело с номером {case_id} не найдено или уже закрыто.")
                return

            user_id = message.from_user.id
            current_answers = appealManager.get_appeal(case_id).get('council_answers', []) or []
            if any(answer['user_id'] == user_id for answer in current_answers):
                bot.send_message(message.chat.id, "Вы уже предоставили ответ по этому делу.")
                return

            user_states[user_id] = {
                'state': 'awaiting_council_main_arg',
                'case_id': case_id,
                'temp_answer': {
                    'user_id': user_id,
                    'responder_info': f"Ответ от {message.from_user.first_name} (@{message.from_user.username})"
                }
            }
            bot.send_message(message.chat.id, f"Изложите, пожалуйста, основные контраргументы Совета по делу #{case_id}.")
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "Неверный формат. Используйте: /reply [номер_дела]")

    # Единый обработчик для состояний редакторов
    @bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('state', '').startswith('awaiting_council_'))
    def handle_council_dialogue(message):
        user_id = message.from_user.id
        state_data = user_states[user_id]
        state = state_data.get('state')
        case_id = state_data.get('case_id')
        temp_answer = state_data.get('temp_answer')

        if state == 'awaiting_council_main_arg':
            temp_answer['main_arg'] = message.text
            user_states[user_id]['state'] = 'awaiting_council_q1'
            bot.send_message(message.chat.id, "Вопрос 1/2: На каких пунктах устава или предыдущих решениях основывалась позиция Совета?")

        elif state == 'awaiting_council_q1':
            temp_answer['q1'] = message.text
            user_states[user_id]['state'] = 'awaiting_council_q2'
            bot.send_message(message.chat.id, "Вопрос 2/2: Какие аргументы заявителя вы считаете несостоятельными и почему?")

        elif state == 'awaiting_council_q2':
            temp_answer['q2'] = message.text
            appealManager.add_council_answer(case_id, temp_answer)
            bot.send_message(message.chat.id, f"Ваш ответ по делу #{case_id} принят и будет учтен при вынесении вердикта. Спасибо!")
            user_states.pop(user_id, None) # Завершаем диалог с этим редактором

            # Проверяем, нужно ли завершать дело досрочно
            appeal = appealManager.get_appeal(case_id)
            if appeal and appeal.get('expected_responses') is not None:
                if len(appeal.get('council_answers', [])) >= appeal['expected_responses']:
                    print(f"Все {appeal['expected_responses']} ответов по делу #{case_id} собраны. Завершаю досрочно.")
                    finalize_appeal(case_id, bot)