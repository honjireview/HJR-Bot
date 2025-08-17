# -*- coding: utf-8 -*-
"""
Обработчики подачи апелляции. Делегирует парсинг ссылок и операции с Telegram
в handlers.parse_link и handlers.telegram_helpers. При обработке ссылок:
- пытаемся скопировать/переслать сообщение (copy/forward) — если успешно, принимаем ссылку;
- если copy/forward не удался — показываем подробную ошибку и предлагаем действия.
"""
import logging
import random
from datetime import datetime

from telebot import types

import appealManager

from .parse_link import parse_message_link
from .telegram_helpers import get_chat_safe, copy_or_forward_message
from .council_helpers import is_link_from_council, resolve_council_id, request_counter_arguments

log = logging.getLogger("hjr-bot.applicant_flow")


def register_applicant_handlers(bot, user_states: dict):
    """
    Регистрирует обработчики. user_states — словарь user_id -> dict(state=..., items=[...], case_id...)
    """

    @bot.message_handler(commands=["start"])
    def send_welcome(message):
        user_states.pop(message.from_user.id, None)
        log.info(f"[dialog] /start user={message.from_user.id}")
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(
            message.chat.id,
            "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс.",
            reply_markup=markup
        )

    @bot.message_handler(commands=["cancel"])
    def cancel_process(message):
        user_id = message.from_user.id
        state = user_states.pop(user_id, None)
        if state and "case_id" in state:
            try:
                appealManager.delete_appeal(state["case_id"])
            except Exception:
                log.exception(f"[cancel] failed to delete appeal {state.get('case_id')}")
        bot.send_message(message.chat.id, "Процесс подачи апелляции отменен.", reply_markup=types.ReplyKeyboardRemove())

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        user_states[user_id] = {"state": "collecting_items", "items": []}
        log.info(f"[dialog] start_appeal user={user_id} state=collecting_items")
        markup = types.InlineKeyboardMarkup()
        done_button = types.InlineKeyboardButton("Готово, я все отправил(а)", callback_data="done_collecting")
        markup.add(done_button)
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        bot.send_message(
            call.message.chat.id,
            "Пожалуйста, пришлите ссылки на сообщения (t.me/...) из приватной группы/канала Совета, которые вы хотите оспорить. Когда закончите, нажмите 'Готово'.",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "done_collecting")
    def handle_done_collecting_callback(call):
        user_id = call.from_user.id
        state_data = user_states.get(user_id)
        if not state_data or not state_data.get("items"):
            try:
                bot.answer_callback_query(call.id, "Вы ничего не отправили.", show_alert=True)
            except Exception:
                bot.send_message(call.message.chat.id, "Вы ничего не отправили.")
            return
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        process_collected_items(bot, user_id, call.message, user_states)

    def process_collected_items(bot, user_id, message, user_states):
        state_data = user_states.get(user_id)
        if not state_data:
            return

        full_decision_text, poll_count, total_voters = "", 0, None
        for item in state_data["items"]:
            poll = getattr(item, "poll", None)
            text = getattr(item, "text", None)
            if poll:
                poll_count += 1
                total_voters = getattr(poll, "total_voter_count", total_voters)
                options_text = "\n".join([f"- {opt.text}: {getattr(opt, 'voter_count', 0)} голосов" for opt in poll.options])
                full_decision_text += f"\n\n--- Опрос ---\nВопрос: {poll.question}\n{options_text}"
            elif text:
                full_decision_text += f"\n\n--- Сообщение ---\n{text}"
            else:
                try:
                    if isinstance(item, dict):
                        if "poll" in item:
                            p = item["poll"]
                            poll_count += 1
                            total_voters = p.get("total_voter_count", total_voters)
                            options_text = "\n".join([f"- {opt.get('text','')}: {opt.get('voter_count',0)} голосов" for opt in p.get("options",[])])
                            full_decision_text += f"\n\n--- Опрос ---\nВопрос: {p.get('question','')}\n{options_text}"
                        if "text" in item:
                            full_decision_text += f"\n\n--- Сообщение ---\n{item.get('text','')}"
                except Exception:
                    pass

        if poll_count > 1:
            bot.send_message(message.chat.id, "Ошибка: Вы можете оспорить только одно голосование за раз. Начните заново: /start")
            user_states.pop(user_id, None)
            return

        case_id = random.randint(10000, 99999)
        user_states[user_id]["case_id"] = case_id
        initial_data = {
            "applicant_chat_id": message.chat.id,
            "decision_text": full_decision_text.strip(),
            "total_voters": total_voters,
            "status": "collecting",
            "created_at": datetime.utcnow().isoformat()
        }
        try:
            appealManager.create_appeal(case_id, initial_data)
            log.info(f"Appeal #{case_id} created/updated.")
        except Exception:
            log.exception(f"[appeal-create] failed to create/update appeal #{case_id}")

        bot.send_message(message.chat.id, f"Все объекты приняты. Вашему делу присвоен номер #{case_id}.")

        if poll_count == 1:
            user_states[user_id]["state"] = "awaiting_vote_response"
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
        else:
            user_states[user_id]["state"] = "awaiting_main_argument"
            bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")

    @bot.message_handler(
        func=lambda message: str(user_states.get(message.from_user.id, {}).get("state", "")).startswith("awaiting_")
                             or user_states.get(message.from_user.id, {}).get("state") == "collecting_items",
        content_types=["text", "document"]
    )
    def handle_dialogue_messages(message):
        user_id = message.from_user.id
        state_data = user_states.get(user_id)
        if not state_data:
            return

        state = state_data.get("state")
        case_id = state_data.get("case_id")

        # --- собираем ссылки/сообщения ---
        if state == "collecting_items":
            if message.content_type == "text":
                parsed = parse_message_link(message.text)
                if parsed:
                    from_chat_id, msg_id = parsed
                    log.info(f"[collect] parsed from_chat_id={from_chat_id} msg_id={msg_id}")

                    # Попытка получить объект чата (информативно)
                    parsed_chat = get_chat_safe(bot, from_chat_id)
                    if not parsed_chat:
                        # Если бот не может получить чат — предложить добавить бота
                        log.info(f"[collect] bot cannot get_chat for parsed {from_chat_id}")
                        bot.send_message(
                            message.chat.id,
                            "Не удалось получить сообщение по ссылке. Пожалуйста, добавьте бота (@hjrmainbot) в приватную группу/канал, "
                            "чтобы он мог получить сообщение, и попробуйте снова.",
                            reply_markup=types.ReplyKeyboardRemove()
                        )
                        return

                    # Попытка copy/forward — делаем это в первую очередь (так было в рабочем варианте раньше)
                    msg_obj = None
                    try:
                        msg_obj = copy_or_forward_message(bot, message.chat.id, from_chat_id, msg_id)
                    except Exception as e:
                        log.warning(f"[collect] copy_or_forward raised unexpected error: {e}")

                    if msg_obj:
                        # Приняли ссылку — сохраняем объект
                        state_data["items"].append(msg_obj)
                        log.info(f"[collect] accepted (copied/forwarded), items={len(state_data['items'])}")

                        # Если ссылка не совпадает со строго заданным EDITORS_CHANNEL_ID — логируем и уведомляем,
                        # но не отвергаем, т.к. успешный copy/forward означает доступ бота к сообщению.
                        if not is_link_from_council(bot, from_chat_id):
                            resolved = resolve_council_id()
                            log.warning(f"[collect] link from unexpected chat: parsed={from_chat_id} resolved={resolved}")
                            try:
                                bot.send_message(
                                    message.chat.id,
                                    "Ссылка принята, но она указывает на чат/канал, отличный от основного канала Совета. "
                                    "Если это ошибка — проверьте EDITORS_CHANNEL_ID. (Ссылка всё же принята, т.к. бот смог получить сообщение.)",
                                    reply_markup=types.ReplyKeyboardRemove()
                                )
                            except Exception:
                                pass
                        else:
                            # Обычное подтверждение
                            try:
                                bot.send_message(message.chat.id, f"Ссылка подтверждена и принята ({len(state_data['items'])}).", reply_markup=types.ReplyKeyboardRemove())
                            except Exception:
                                pass
                        return

                    # Если не удалось скопировать/переслать — тогда даём подробное объяснение и проверяем соответствие каналу
                    log.info(f"[collect] copy/forward failed for {from_chat_id}/{msg_id}")
                    # Если ссылка явно не из нужного чата, даём информативное сообщение
                    if not is_link_from_council(bot, from_chat_id):
                        resolved = resolve_council_id()
                        log.info(f"[collect] link rejected: parsed={from_chat_id} resolved={resolved}")
                        try:
                            if resolved:
                                bot.send_message(
                                    message.chat.id,
                                    "Ссылка должна вести на сообщение из приватной группы/канала Совета.\n"
                                    f"В ссылке обнаружен чат: {from_chat_id}. Ожидался: {resolved}.\n"
                                    "Проверьте, что вы присылаете ссылку именно из группы/канала Совета и что EDITORS_CHANNEL_ID корректно задан.",
                                    reply_markup=types.ReplyKeyboardRemove()
                                )
                            else:
                                bot.send_message(
                                    message.chat.id,
                                    "Не удалось получить сообщение по ссылке. Убедитесь, что бот добавлен в группу/канал и что ссылка корректна.",
                                    reply_markup=types.ReplyKeyboardRemove()
                                )
                        except Exception:
                            pass
                        return
                    else:
                        # Ссылка вроде бы из нужного чата, но copy/forward не сработал — даём рекомендации
                        bot.send_message(
                            message.chat.id,
                            "Не удалось получить сообщение по ссылке, хотя ссылка ведёт в ожидаемый чат. Возможно, бот был удалён из группы/канала или у него нет прав на чтение. "
                            "Пожалуйста, проверьте права бота и повторите попытку.",
                            reply_markup=types.ReplyKeyboardRemove()
                        )
                        return

            # не распознана ссылка как t.me/...
            bot.send_message(
                message.chat.id,
                "Пришлите, пожалуйста, ссылку на сообщение (t.me/...), только из приватной группы/канала Совета.",
                reply_markup=types.ReplyKeyboardRemove()
            )
            return

        # --- вопросы/логика после принятия ссылок ---
        elif state == "awaiting_vote_response":
            appeal = appealManager.get_appeal(case_id)
            if not appeal:
                bot.send_message(message.chat.id, "Ошибка: дело не найдено.")
                user_states.pop(user_id, None)
                return
            text = (message.text or "").strip()
            if text.startswith("Да"):
                expected_responses = (appeal.get("total_voters") or 1) - 1
                appealManager.update_appeal(case_id, "expected_responses", expected_responses)
                user_states[user_id]["state"] = "awaiting_main_argument"
                bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            elif text.startswith("Нет"):
                bot.send_message(message.chat.id, "Согласно правилам, все участники должны принимать участие в голосовании. Ваша апелляция отклонена.")
                attempt_case = case_id
                try:
                    appealManager.delete_appeal(case_id)
                except Exception:
                    log.exception(f"[vote_response] failed to delete appeal {attempt_case}")
                user_states.pop(user_id, None)
            else:
                bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа.")

        elif state == "awaiting_main_argument":
            appealManager.update_appeal(case_id, "applicant_arguments", message.text)
            user_states[user_id]["state"] = "awaiting_q1"
            bot.send_message(message.chat.id, "Спасибо. Теперь ответьте на уточняющие вопросы.", reply_markup=types.ReplyKeyboardRemove())
            bot.send_message(message.chat.id, "Вопрос 1/3: Какой пункт устава, по вашему мнению, был нарушен?")

        elif state == "awaiting_q1":
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get("applicant_answers", {}) or {}
                current_answers["q1"] = message.text
                appealManager.update_appeal(case_id, "applicant_answers", current_answers)
            user_states[user_id]["state"] = "awaiting_q2"
            bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")

        elif state == "awaiting_q2":
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get("applicant_answers", {}) or {}
                current_answers["q2"] = message.text
                appealManager.update_appeal(case_id, "applicant_answers", current_answers)
            user_states[user_id]["state"] = "awaiting_q3"
            bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")

        elif state == "awaiting_q3":
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get("applicant_answers", {}) or {}
                current_answers["q3"] = message.text
                appealManager.update_appeal(case_id, "applicant_answers", current_answers)
            user_states.pop(user_id, None)
            log.info(f"[flow] q3 saved; dialog closed case_id={case_id}")
            try:
                request_counter_arguments(bot, case_id)
            except Exception:
                log.exception(f"[flow] failed to request counter arguments for case {case_id}")