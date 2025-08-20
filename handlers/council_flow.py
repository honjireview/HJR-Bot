# -*- coding: utf-8 -*-
import logging
import appealManager
from .council_helpers import resolve_council_id

log = logging.getLogger("hjr-bot.council_flow")
CHARACTER_LIMIT = 4000

COUNCIL_STATE_PREFIX = "council_"
CouncilStates = {
    "MAIN_ARG": f"{COUNCIL_STATE_PREFIX}main_arg",
    "Q1": f"{COUNCIL_STATE_PREFIX}q1",
    "Q2": f"{COUNCIL_STATE_PREFIX}q2",
}

def register_council_handlers(bot):
    """
    Регистрирует обработчики для процесса ОТВЕТА СОВЕТА на апелляцию.
    """
    @bot.message_handler(commands=['reply'], chat_types=['private'])
    def handle_reply(message):
        # ... (код без изменений) ...
        user_id = message.from_user.id
        is_editor = appealManager.is_user_an_editor(bot, user_id, resolve_council_id())
        if not is_editor:
            return

        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            bot.reply_to(message, "Неверный формат. Используйте: `/reply <номер_дела>`")
            return

        case_id = int(parts[1])
        appeal = appealManager.get_appeal(case_id)

        if not appeal:
            bot.reply_to(message, f"Дело #{case_id} не найдено.")
            return
        if appeal.get("status") != 'collecting':
            bot.reply_to(message, f"Сбор контраргументов по делу #{case_id} уже завершен.")
            return

        data = {"case_id": case_id, "answers": {}}
        appealManager.set_user_state(user_id, CouncilStates["MAIN_ARG"], data)
        log.info(f"[COUNCIL_FLOW] User {user_id} starts reply for case #{case_id}. State set to {CouncilStates['MAIN_ARG']}.")
        bot.send_message(message.chat.id, f"Вы отвечаете по делу #{case_id}.\n\nПожалуйста, изложите ваши основные контраргументы.")

    @bot.message_handler(
        func=lambda message: (
                appealManager.get_user_state(message.from_user.id) is not None and
                str(appealManager.get_user_state(message.from_user.id).get('state', '')).startswith(COUNCIL_STATE_PREFIX) and
                message.chat.type == 'private'
        ),
        content_types=['text']
    )
    def handle_council_fsm(message):
        user_id = message.from_user.id

        if message.text.startswith('/'):
            if message.text.strip() != '/cancel':
                bot.reply_to(message, "Пожалуйста, завершите процесс ответа или отмените его командой /cancel.")
            return

        state_data = appealManager.get_user_state(user_id)
        state = state_data.get("state")
        data = state_data.get("data", {})
        case_id = data.get("case_id")

        log.info(f"[COUNCIL_FLOW] Handling FSM for user {user_id}, case #{case_id}, state: {state}")

        if len(message.text) > CHARACTER_LIMIT:
            bot.reply_to(message, f"Вы превысили лимит символов ({CHARACTER_LIMIT}).")
            return

        current_answers = data.get("answers", {})

        if state == CouncilStates["MAIN_ARG"]:
            current_answers["main_arg"] = message.text
            data["answers"] = current_answers
            next_state = CouncilStates["Q1"]
            appealManager.set_user_state(user_id, next_state, data)
            log.info(f"[COUNCIL_FLOW] User {user_id} provided main_arg for case #{case_id}. New state: {next_state}")
            bot.send_message(message.chat.id, "Вопрос 1/2: На каких пунктах устава или правил основывается ваша позиция?")

        elif state == CouncilStates["Q1"]:
            current_answers["q1"] = message.text
            data["answers"] = current_answers
            next_state = CouncilStates["Q2"]
            appealManager.set_user_state(user_id, next_state, data)
            log.info(f"[COUNCIL_FLOW] User {user_id} provided q1 for case #{case_id}. New state: {next_state}")
            bot.send_message(message.chat.id, "Вопрос 2/2: Как вы оцениваете аргументы заявителя? Считаете ли вы их релевантными?")

        elif state == CouncilStates["Q2"]:
            current_answers["q2"] = message.text

            # ИСПРАВЛЕНО: Проверяем контраргументы перед сохранением
            main_args = current_answers.get("main_arg", "")
            if not appealManager.are_arguments_meaningful(main_args):
                bot.send_message(message.chat.id, "Ваши основные контраргументы кажутся слишком короткими или несодержательными. Пожалуйста, изложите вашу позицию более подробно.")
                # Возвращаем пользователя на шаг ввода основных контраргументов
                appealManager.set_user_state(user_id, CouncilStates["MAIN_ARG"], data)
                return

            responder_info = f"{message.from_user.first_name} (@{message.from_user.username or 'скрыто'})"
            current_answers["responder_info"] = responder_info

            log.info(f"[COUNCIL_FLOW] User {user_id} provided q2 for case #{case_id}. Finalizing and saving answer.")
            appealManager.add_council_answer(case_id, current_answers)
            appealManager.delete_user_state(user_id)
            log.info(f"[COUNCIL_FLOW] State for user {user_id} deleted. Reply process finished.")
            bot.send_message(message.chat.id, f"Спасибо, ваш ответ по делу #{case_id} принят.")