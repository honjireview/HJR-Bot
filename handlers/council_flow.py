# -*- coding: utf-8 -*-

import telebot
from telebot import types
import appealManager
import geminiProcessor
import config

def finalize_appeal(case_id, bot):
    appeal = appealManager.get_appeal(case_id)
    if not appeal or appeal.get('status') == 'closed':
        return

    print(f"Завершаю рассмотрение дела #{case_id}.")
    appealManager.update_appeal(case_id, 'status', 'closed')

    ai_verdict = geminiProcessor.get_verdict_from_gemini(case_id)
    appealManager.update_appeal(case_id, 'ai_verdict', ai_verdict)

    # ... (формирование и отправка отчета) ...
    final_report_text = f"⚖️ **Рассмотрение апелляции №{case_id}** ⚖️\n\n..."

    try:
        bot.send_message(config.APPEALS_CHANNEL_ID, final_report_text, parse_mode="Markdown")
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
    def handle_counter_argument_command(message):
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

            user_states[user_id] = {'state': 'awaiting_council_main_arg', 'case_id': case_id}
            bot.send_message(message.chat.id, f"Изложите, пожалуйста, основные контраргументы Совета по делу #{case_id}.")
        except (ValueError, IndexError):
            bot.send_message(message.chat.id, "Неверный формат. Используйте: /reply [номер_дела]")

    # ... (здесь будет единый обработчик для состояний редакторов, аналогично applicant_flow)