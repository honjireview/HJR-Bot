# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta
import appealManager
from .telegram_helpers import validate_appeal_link
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.review_flow")

REVIEW_STATE_PREFIX = "review_"
ReviewStates = {
    "WAITING_POLL": f"{REVIEW_STATE_PREFIX}waiting_poll",
    "WAITING_ARG": f"{REVIEW_STATE_PREFIX}waiting_arg",
}

def register_review_handlers(bot):
    """
    Регистрирует обработчики для процесса ПЕРЕСМОТРА вердикта ИИ.
    """
    @bot.message_handler(commands=['recase'], chat_types=['private'])
    def handle_recase(message):
        user_id = message.from_user.id
        is_editor = appealManager.is_user_an_editor(bot, user_id, resolve_council_id())
        if not is_editor:
            return

        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            bot.reply_to(message, "Неверный формат. Используйте: `/recase <номер_дела>`")
            return

        case_id = int(parts[1])
        appeal = appealManager.get_appeal(case_id)

        if not appeal:
            bot.reply_to(message, f"Дело #{case_id} не найдено.")
            return
        if appeal.get("status") != 'closed':
            bot.reply_to(message, f"Пересмотр возможен только для дел со статусом 'closed'. Статус этого дела: '{appeal.get('status')}'.")
            return
        if appeal.get("is_reviewed"):
            bot.reply_to(message, "Это дело уже было пересмотрено, повторный пересмотр невозможен.")
            return

        data = {"case_id": case_id}
        appealManager.set_user_state(user_id, ReviewStates["WAITING_POLL"], data)
        bot.send_message(message.chat.id, f"Вы инициировали пересмотр дела №{case_id}.\n\nПожалуйста, пришлите ссылку на закрытое голосование Совета, по результатам которого было принято решение о пересмотре.")

    @bot.message_handler(commands=['replyrecase'], chat_types=['private'])
    def handle_reply_recase(message):
        user_id = message.from_user.id
        is_editor = appealManager.is_user_an_editor(bot, user_id, resolve_council_id())
        if not is_editor:
            return

        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            bot.reply_to(message, "Неверный формат. Используйте: `/replyrecase <номер_дела>`")
            return

        case_id = int(parts[1])
        appeal = appealManager.get_appeal(case_id)
        if not appeal or appeal.get("status") != 'reviewing':
            bot.reply_to(message, f"Дело #{case_id} не найдено или сейчас не находится на стадии пересмотра.")
            return

        data = {"case_id": case_id}
        appealManager.set_user_state(user_id, ReviewStates["WAITING_ARG"], data)
        bot.send_message(message.chat.id, f"Изложите ваши новые аргументы или доказательства по делу №{case_id}, которые не были учтены в первом вердикте.")

    @bot.message_handler(
        func=lambda message: (
                appealManager.get_user_state(message.from_user.id) is not None and
                str(appealManager.get_user_state(message.from_user.id).get('state', '')).startswith(REVIEW_STATE_PREFIX)
        ),
        content_types=['text']
    )
    def handle_review_fsm(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        state = state_data.get("state")
        data = state_data.get("data", {})
        case_id = data.get("case_id")

        if state == ReviewStates["WAITING_POLL"]:
            is_valid, result = validate_appeal_link(bot, message.text, user_chat_id=message.chat.id)
            if not is_valid:
                bot.reply_to(message, f"Ошибка: {result}")
                return

            if result.get("type") != "poll":
                bot.reply_to(message, "Ошибка: Присланная ссылка ведет не на опрос.")
                return

            poll_data = result.get("poll", {})
            question = poll_data.get("question", "").lower()

            # Строгая проверка текста опроса
            if "пересмотр" not in question or str(case_id) not in question:
                bot.reply_to(message, f"Текст опроса не соответствует делу №{case_id} или не содержит слова 'пересмотр'. Операция отменена.")
                appealManager.delete_user_state(user_id)
                return

            # Проверка, что голосование "За" победило
            options = poll_data.get("options", [])
            for_votes = 0
            for opt in options:
                if "за" in opt.get("text", "").lower():
                    for_votes = opt.get("voter_count", 0)

            if for_votes <= (poll_data.get("total_voter_count", 0) / 2):
                bot.reply_to(message, "Решение о пересмотре не было принято большинством голосов. Операция отменена.")
                appealManager.delete_user_state(user_id)
                return

            # Все проверки пройдены
            appealManager.update_appeal(case_id, "status", "reviewing")
            appealManager.update_appeal(case_id, "is_reviewed", True)

            review_data = {"poll": poll_data}
            appealManager.update_appeal(case_id, "review_data", review_data)

            # Устанавливаем новый таймер
            expires_at = datetime.utcnow() + timedelta(hours=24)
            appealManager.update_appeal(case_id, "timer_expires_at", expires_at)

            bot.send_message(message.chat.id, f"Голосование по делу №{case_id} принято. Начался 24-часовой сбор дополнительных аргументов от членов Совета.")

            council_chat_id = resolve_council_id()
            appeal = appealManager.get_appeal(case_id)
            thread_id = appeal.get("message_thread_id")
            bot.send_message(council_chat_id, f"📣 Пересмотр дела №{case_id} одобрен Советом. \nЧлены Совета могут предоставить дополнительные аргументы в течение 24 часов через команду `/replyrecase {case_id}` в личном чате с ботом.", message_thread_id=thread_id)
            appealManager.delete_user_state(user_id)

        elif state == ReviewStates["WAITING_ARG"]:
            if not appealManager.are_arguments_meaningful(message.text):
                bot.reply_to(message, "Ваши аргументы слишком короткие. Пожалуйста, изложите позицию более развернуто.")
                return

            appeal = appealManager.get_appeal(case_id)
            review_data = appeal.get("review_data", {}) or {}
            new_args = review_data.get("new_arguments", [])

            author_info = f"{message.from_user.first_name} (@{message.from_user.username or 'скрыто'})"
            new_args.append({
                "author": author_info,
                "argument": message.text
            })

            review_data["new_arguments"] = new_args
            appealManager.update_appeal(case_id, "review_data", review_data)
            bot.send_message(message.chat.id, f"Ваши новые аргументы по делу №{case_id} приняты.")
            appealManager.delete_user_state(user_id)