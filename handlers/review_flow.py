# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta
import appealManager
from .telegram_helpers import validate_appeal_link
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.review_flow")

# Состояние теперь будет привязано к ID чата, а не пользователя
REVIEW_STATE_WAITING_POLL = "review_state_waiting_poll_for_chat"
# Это состояние для ЛС, как и раньше
REVIEW_STATE_WAITING_ARG = "review_state_waiting_arg_for_user"

def register_review_handlers(bot):
    """
    Регистрирует обработчики для процесса ПЕРЕСМОТРА вердикта ИИ.
    """
    @bot.message_handler(commands=['recase'])
    def handle_recase(message):
        # Эта команда теперь работает только в группе Совета
        if message.chat.type not in ['group', 'supergroup']:
            bot.reply_to(message, "Эту команду можно использовать только в чате Совета.")
            return

        council_id = resolve_council_id()
        if message.chat.id != council_id:
            bot.reply_to(message, "Эту команду можно использовать только в официальном чате Совета Редакторов.")
            return

        user_id = message.from_user.id
        is_editor = appealManager.is_user_an_editor(bot, user_id, council_id)
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
            bot.reply_to(message, f"Пересмотр возможен только для закрытых дел.")
            return
        if appeal.get("is_reviewed"):
            bot.reply_to(message, "Это дело уже было пересмотрено.")
            return

        # Устанавливаем состояние для ЧАТА, чтобы бот ждал ссылку именно здесь
        chat_state_key = f"chat_{message.chat.id}"
        data = {"case_id": case_id, "initiator_id": user_id}
        appealManager.set_user_state(chat_state_key, REVIEW_STATE_WAITING_POLL, data)
        log.info(f"[REVIEW] Установлено состояние {REVIEW_STATE_WAITING_POLL} для чата: {message.chat.id}")

        # Бот отвечает в группе
        bot.reply_to(message, f"Инициирован пересмотр дела №{case_id}. Ожидаю ссылку на закрытое голосование Совета по этому вопросу.")

    @bot.message_handler(commands=['replyrecase'])
    def handle_reply_recase(message):
        # Эта команда по-прежнему работает только в ЛС
        if message.chat.type != 'private':
            bot.reply_to(message, "Эту команду можно использовать только в личном чате с ботом.")
            return

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
            bot.reply_to(message, f"Дело #{case_id} не найдено или сейчас не на стадии пересмотра.")
            return

        data = {"case_id": case_id}
        appealManager.set_user_state(user_id, REVIEW_STATE_WAITING_ARG, data)
        bot.send_message(message.chat.id, f"Изложите ваши новые аргументы по делу №{case_id}.")

    # Новый обработчик, который "слушает" ссылки ТОЛЬКО в чате, где была вызвана /recase
    @bot.message_handler(
        func=lambda message: (
                message.chat.type in ['group', 'supergroup'] and
                appealManager.get_user_state(f"chat_{message.chat.id}") is not None and
                "t.me/" in message.text
        ),
        content_types=['text']
    )
    def handle_review_poll_link(message):
        chat_id_key = f"chat_{message.chat.id}"
        state_data = appealManager.get_user_state(chat_id_key)

        # Двойная проверка, что мы в правильном состоянии
        if state_data.get("state") != REVIEW_STATE_WAITING_POLL:
            return

        case_id = state_data.get("data", {}).get("case_id")
        log.info(f"[REVIEW_FSM] В чате {message.chat.id} получена ссылка для пересмотра дела #{case_id}")

        is_valid, result = validate_appeal_link(bot, message.text, user_chat_id=message.chat.id)
        if not is_valid:
            bot.reply_to(message, f"Ошибка валидации ссылки: {result}")
            return

        if result.get("type") != "poll":
            bot.reply_to(message, "Ошибка: Присланная ссылка ведет не на опрос.")
            return

        poll_data = result.get("poll", {})
        question = poll_data.get("question", "").lower()

        if "пересмотр" not in question or str(case_id) not in question:
            bot.reply_to(message, f"Текст опроса не соответствует делу №{case_id} или не содержит слова 'пересмотр'.")
            return

        options = poll_data.get("options", [])
        for_votes = 0
        for opt in options:
            if "за" in opt.get("text", "").lower():
                for_votes = opt.get("voter_count", 0)

        if for_votes <= (poll_data.get("total_voter_count", 0) / 2):
            bot.reply_to(message, "Решение о пересмотре не было принято большинством голосов.")
            appealManager.delete_user_state(chat_id_key) # Сбрасываем состояние чата
            return

        log.info(f"[REVIEW_FSM] Все проверки для пересмотра дела #{case_id} пройдены.")
        appealManager.update_appeal(case_id, "status", "reviewing")
        appealManager.update_appeal(case_id, "is_reviewed", True)

        review_data = {"poll": poll_data}
        appealManager.update_appeal(case_id, "review_data", review_data)

        expires_at = datetime.utcnow() + timedelta(hours=24)
        appealManager.update_appeal(case_id, "timer_expires_at", expires_at)

        bot.reply_to(message, f"Голосование по делу №{case_id} принято. Начался 24-часовой сбор дополнительных аргументов.")

        appeal = appealManager.get_appeal(case_id)
        thread_id = appeal.get("message_thread_id")
        bot.send_message(message.chat.id, f"📣 Члены Совета могут предоставить аргументы через команду `/replyrecase {case_id}` в личном чате с ботом.", message_thread_id=thread_id)
        appealManager.delete_user_state(chat_id_key)

    # Обработчик для сбора аргументов в ЛС
    @bot.message_handler(
        func=lambda message: (
                appealManager.get_user_state(message.from_user.id) is not None and
                str(appealManager.get_user_state(message.from_user.id).get('state', '')) == REVIEW_STATE_WAITING_ARG
        ),
        content_types=['text']
    )
    def handle_review_argument_fsm(message):
        user_id = message.from_user.id
        state_data = appealManager.get_user_state(user_id)
        case_id = state_data.get("data", {}).get("case_id")

        if not appealManager.are_arguments_meaningful(message.text):
            bot.reply_to(message, "Ваши аргументы слишком короткие. Пожалуйста, изложите позицию более развернуто.")
            return

        appeal = appealManager.get_appeal(case_id)
        review_data = appeal.get("review_data", {}) or {}
        new_args = review_data.get("new_arguments", [])

        author_info = f"{message.from_user.first_name} (@{message.from_user.username or 'скрыто'})"
        new_args.append({"author": author_info, "argument": message.text})

        review_data["new_arguments"] = new_args
        appealManager.update_appeal(case_id, "review_data", review_data)
        log.info(f"[REVIEW_FSM] Пользователь {user_id} добавил новый аргумент к делу #{case_id}.")
        bot.send_message(message.chat.id, f"Ваши новые аргументы по делу №{case_id} приняты.")
        appealManager.delete_user_state(user_id)