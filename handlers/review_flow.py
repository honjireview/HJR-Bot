# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta
import appealManager
from .telegram_helpers import validate_appeal_link
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.review_flow")

# Определяем состояния для FSM
REVIEW_STATE_WAITING_ARG = "review_state_waiting_arg_for_user"

def register_review_handlers(bot):
    """
    Регистрирует обработчики для процесса ПЕРЕСМОТРА вердикта ИИ.
    """
    @bot.message_handler(commands=['recase'])
    def handle_recase(message):
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

        log.info(f"[REVIEW] Инициирован пересмотр дела #{case_id} пользователем {user_id}")

        try:
            # Бот сам создает и отправляет голосование
            poll_question = f"Пересмотр вердикта по делу №{case_id}"
            poll_options = ['Да, пересмотреть', 'Нет, оставить в силе']

            sent_poll_msg = bot.send_poll(
                chat_id=message.chat.id,
                question=poll_question,
                options=poll_options,
                is_anonymous=False,
                open_period=18000 # 5 часов в секундах
            )

            # Сохраняем информацию о голосовании в базу
            review_data = {
                "poll_message_id": sent_poll_msg.message_id,
                "poll_id": sent_poll_msg.poll.id
            }
            appealManager.update_appeal(case_id, "review_data", review_data)
            appealManager.update_appeal(case_id, "status", "review_poll_pending")

            # Устанавливаем таймер в базе данных на 5 часов
            expires_at = datetime.utcnow() + timedelta(hours=5)
            appealManager.update_appeal(case_id, "timer_expires_at", expires_at)

            log.info(f"Создано голосование для пересмотра дела #{case_id}. Message ID: {sent_poll_msg.message_id}")
            bot.reply_to(message, f"Создано голосование для пересмотра дела №{case_id}. Голосование будет автоматически закрыто через 5 часов.")

        except Exception as e:
            log.error(f"Не удалось создать голосование для пересмотра дела #{case_id}: {e}")
            bot.reply_to(message, "Произошла ошибка при создании голосования.")

    @bot.message_handler(commands=['replyrecase'])
    def handle_reply_recase(message):
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
            bot.reply_to(message, f"Дело #{case_id} не найдено или сейчас не на стадии сбора аргументов для пересмотра.")
            return

        data = {"case_id": case_id}
        appealManager.set_user_state(user_id, REVIEW_STATE_WAITING_ARG, data)
        bot.send_message(message.chat.id, f"Изложите ваши новые аргументы по делу №{case_id}.")

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