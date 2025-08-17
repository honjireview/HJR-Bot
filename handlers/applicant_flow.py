# -*- coding: utf-8 -*-

import telebot
from telebot import types
import random
import os
import pandas as pd
import io
import re
import logging
from datetime import datetime, timedelta

import appealManager
from .council_flow import finalize_appeal

# Railway の環境変数: プライベートグループ（評議会）の chat_id（例: -100xxxxxxxxxx）
EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')
# 検証対象のチャットIDは EDITORS_CHANNEL_ID を使用
COUNCIL_CHAT_ID = EDITORS_CHANNEL_ID
# Кэш нормализованного chat_id источника (может быть скорректирован в рантайме)
_RESOLVED_COUNCIL_ID = {'value': None}

log = logging.getLogger("hjr-bot")

def register_applicant_handlers(bot, user_states):
    """
    Регистрирует обработчики для процесса подачи апелляции.
    """

    # Нормализация COUNCIL_CHAT_ID из окружения (@username | внутренний id | -100...)
    def _resolve_council_chat_id():
        if _RESOLVED_COUNCIL_ID['value'] is not None:
            return _RESOLVED_COUNCIL_ID['value']
        raw = (COUNCIL_CHAT_ID or "").strip()
        if not raw:
            log.warning("[council-id] EDITORS_CHANNEL_ID пуст. Строгая проверка отключена.")
            _RESOLVED_COUNCIL_ID['value'] = None
            return None
        try:
            if raw.startswith("@"):
                chat = bot.get_chat(raw)
                _RESOLVED_COUNCIL_ID['value'] = int(chat.id)
                log.info(f"[council-id] @{raw} -> { _RESOLVED_COUNCIL_ID['value'] }")
                return _RESOLVED_COUNCIL_ID['value']
            n = int(raw)
            if n > 0:
                _RESOLVED_COUNCIL_ID['value'] = int(f"-100{n}")
                log.info(f"[council-id] internal {n} -> { _RESOLVED_COUNCIL_ID['value'] }")
            else:
                _RESOLVED_COUNCIL_ID['value'] = n
                log.info(f"[council-id] numeric {n}")
            return _RESOLVED_COUNCIL_ID['value']
        except Exception as e:
            try:
                username = raw if raw.startswith("@") else f"@{raw}"
                chat = bot.get_chat(username)
                _RESOLVED_COUNCIL_ID['value'] = int(chat.id)
                log.info(f"[council-id] fallback {username} -> { _RESOLVED_COUNCIL_ID['value'] }")
                return _RESOLVED_COUNCIL_ID['value']
            except Exception as e2:
                log.error(f"[council-id] Невозможно распознать EDITORS_CHANNEL_ID='{raw}': {e} / {e2}")
                _RESOLVED_COUNCIL_ID['value'] = None
                return None

    # Рантайм‑коррекция источника, если ссылка валидна и бот смог получить сообщение
    def _set_council_chat_id_runtime(chat_id: int):
        try:
            _RESOLVED_COUNCIL_ID['value'] = int(chat_id)
            log.warning(f"[council-id] Runtime override установлен: {chat_id}")
        except Exception as e:
            log.error(f"[council-id] Runtime override не применен: {e}")

    # --- ヘルパ: メッセージリンクを解析 ---
    def _parse_message_link(text: str):
        s = (text or "").strip()
        log.debug(f"[link-parse] input='{s}'")
        # 1) Топик: t.me/c/<internal>/<topic_id>/<message_id>
        m = re.search(r'^(?:https?://)?t\.me/c/(\d+)/(\d+)/(\d+)(?:/.*)?(?:\?.*)?$', s)
        if m:
            internal = int(m.group(1))
            topic_id = int(m.group(2))  # noqa: F841
            msg_id = int(m.group(3))
            from_chat_id = int(f"-100{internal}")
            log.info(f"[link-parse] topic link: internal={internal} -> chat_id={from_chat_id}, topic_id={topic_id}, msg_id={msg_id}")
            return from_chat_id, msg_id

        # 2) Приватная: t.me/c/<internal>/<message_id>
        m = re.search(r'^(?:https?://)?t\.me/c/(\d+)/(\d+)(?:/.*)?(?:\?.*)?$', s)
        if m:
            internal = int(m.group(1))
            msg_id = int(m.group(2))
            from_chat_id = int(f"-100{internal}")
            log.info(f"[link-parse] c-link: internal={internal} -> chat_id={from_chat_id}, msg_id={msg_id}")
            return from_chat_id, msg_id

        # 3) Публичная: t.me/<username>/<message_id>
        m = re.search(r'^(?:https?://)?t\.me/([A-Za-z0-9_]{5,})/(\d+)(?:/.*)?(?:\?.*)?$', s)
        if m:
            username = m.group(1)
            msg_id = int(m.group(2))
            try:
                chat = bot.get_chat(f"@{username}")
                log.info(f"[link-parse] public: @{username} -> chat_id={chat.id}, msg_id={msg_id}")
                return chat.id, msg_id
            except Exception as e:
                log.warning(f"[link-parse] resolve @{username} failed: {e}")
                return None

        log.debug("[link-parse] no match")
        return None

    # --- Шаг 1: Начало ---
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_states.pop(message.from_user.id, None)
        log.info(f"[dialog] /start user={message.from_user.id} chat={message.chat.id}")
        markup = types.InlineKeyboardMarkup()
        appeal_button = types.InlineKeyboardButton("Подать апелляцию", callback_data="start_appeal")
        markup.add(appeal_button)
        bot.send_message(
            message.chat.id,
            "Здравствуйте! Это бот для подачи апелляций проекта Honji Review. Нажмите кнопку ниже, чтобы начать процесс.",
            reply_markup=markup
        )

    # 任意: 途中キャンセル
    @bot.message_handler(commands=['cancel'])
    def cancel_process(message):
        if user_states.pop(message.from_user.id, None) is not None:
            bot.send_message(message.chat.id, "Процесс подачи апелляции отменен.", reply_markup=types.ReplyKeyboardRemove())
        else:
            bot.send_message(message.chat.id, "Нет активного процесса для отмены.", reply_markup=types.ReplyKeyboardRemove())

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        user_states[user_id] = {'state': 'collecting_items', 'items': []}
        log.info(f"[dialog] start_appeal user={user_id} state=collecting_items")
        markup = types.InlineKeyboardMarkup()
        done_button = types.InlineKeyboardButton("Готово, я все отправил(а)", callback_data="done_collecting")
        markup.add(done_button)
        bot.send_message(
            call.message.chat.id,
            "Пожалуйста, пришлите ссылки на сообщения (t.me/...) из приватной группы Совета, которые вы хотите оспорить. "
            "Обычные пересылки не принимаются. Когда закончите, нажмите 'Готово'.\n\nДля отмены в любой момент введите /cancel",
            reply_markup=markup
        )

    # --- Шаг 2: Завершение сбора и обработка ---
    @bot.callback_query_handler(func=lambda call: call.data == "done_collecting")
    def handle_done_collecting_callback(call):
        user_id = call.from_user.id
        state_data = user_states.get(user_id)
        items_count = len(state_data.get('items', [])) if state_data else 0
        log.info(f"[dialog] done_collecting user={user_id} items={items_count}")
        if not state_data or not state_data.get('items'):
            bot.answer_callback_query(call.id, "Вы ничего не отправили.", show_alert=True)
            return
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        process_collected_items(bot, call.message, user_states)

    def process_collected_items(bot, message, user_states):
        user_id = message.from_user.id  # фикс: использовать from_user.id, а не chat.id
        state_data = user_states.get(user_id)
        if not state_data:
            log.warning(f"[process] no state for user={user_id}")
            return

        log.info(f"[process] start user={user_id} items={len(state_data.get('items', []))}")
        full_decision_text, all_voters_to_mention, total_voters, poll_count = "", [], None, 0
        for item in state_data['items']:
            if getattr(item, 'content_type', '') == 'poll':
                poll_count += 1
                poll = item.poll
                total_voters = poll.total_voter_count
                options_text = "\n".join([f"- {opt.text}: {opt.voter_count} голосов" for opt in poll.options])
                full_decision_text += f"\n\n--- Опрос ---\nВопрос: {poll.question}\n{options_text}"
            elif getattr(item, 'content_type', '') == 'text':
                full_decision_text += f"\n\n--- Сообщение ---\n{item.text}"
            elif getattr(item, 'content_type', '') == 'document' and item.document.mime_type == 'text/csv':
                try:
                    file_info = bot.get_file(item.document.file_id)
                    downloaded_file = bot.download_file(file_info.file_path)
                    df = pd.read_csv(io.BytesIO(downloaded_file))
                    try:
                        rendered = df.to_markdown(index=False)  # может требовать tabulate
                    except Exception:
                        rendered = df.to_csv(index=False)
                    full_decision_text += "\n\n--- Данные из Google Forms (CSV) ---\n" + rendered
                    mention_col = 'Username' if 'Username' in df.columns else 'UserID' if 'UserID' in df.columns else None
                    if mention_col:
                        all_voters_to_mention.extend(df[mention_col].dropna().astype(str).tolist())
                    log.info(f"[process] CSV parsed rows={len(df)} mention_col={mention_col}")
                except Exception as e:
                    log.error(f"[process] CSV error: {e}")
                    bot.send_message(message.chat.id, f"Ошибка обработки CSV: {e}. Этот файл будет проигнорирован.")

        if poll_count > 1:
            bot.send_message(message.chat.id, "Ошибка: Вы можете оспорить только одно голосование за раз. Начните заново: /start")
            user_states.pop(user_id, None)
            return

        case_id = random.randint(10000, 99999)
        user_states[user_id]['case_id'] = case_id
        initial_data = {
            'applicant_chat_id': message.chat.id,
            'decision_text': full_decision_text.strip(),
            'voters_to_mention': list(set(all_voters_to_mention)),
            'total_voters': total_voters,
            'status': 'collecting'
        }
        appealManager.create_appeal(case_id, initial_data)
        log.info(f"[process] case created id={case_id} poll_count={poll_count} total_voters={total_voters}")
        bot.send_message(message.chat.id, f"Все объекты приняты. Вашему делу присвоен номер #{case_id}.")

        if poll_count == 1:
            user_states[user_id]['state'] = 'awaiting_vote_response'
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
        else:
            user_states[user_id]['state'] = 'awaiting_main_argument'
            bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")

    # 申請者ハンドラ（council状態は除外）
    @bot.message_handler(
        func=lambda message: (
            user_states.get(message.from_user.id) is not None
            and not str(user_states.get(message.from_user.id, {}).get('state', '')).startswith('awaiting_council_')
        ),
        content_types=['text', 'poll', 'document']
    )
    def handle_dialogue_messages(message):
        user_id = message.from_user.id
        state_data = user_states.get(user_id)
        if not state_data: return

        state = state_data.get('state')
        case_id = state_data.get('case_id')
        log.debug(f"[dialog] msg user={user_id} state={state} type={message.content_type}")

        # --- Сбор объектов ---
        if state == 'collecting_items':
            is_forwarded = message.forward_from or message.forward_from_chat
            is_document = message.content_type == 'document'
            is_poll = message.content_type == 'poll'

            if is_forwarded:
                log.info(f"[collect] forwarded rejected user={user_id}")
                bot.send_message(
                    message.chat.id,
                    "Обычные пересылки не принимаются. Пожалуйста, пришлите ссылку на сообщение (t.me/...) из приватной группы Совета."
                )
                return

            if message.content_type == 'text':
                parsed = _parse_message_link(message.text)
                if parsed:
                    from_chat_id, msg_id = parsed
                    expected_id = _resolve_council_chat_id()
                    log.info(f"[collect] parsed from_chat_id={from_chat_id} msg_id={msg_id} expected_id={expected_id}")

                    # ВАЖНО: сначала пытаемся получить сообщение (подтвердить доступ и валидность)
                    try:
                        copied = bot.copy_message(
                            chat_id=message.chat.id,
                            from_chat_id=from_chat_id,
                            message_id=msg_id
                        )
                        # Автокоррекция источника, если окружение отличается
                        if expected_id is None or int(expected_id) != int(from_chat_id):
                            _set_council_chat_id_runtime(int(from_chat_id))

                        state_data['items'].append(copied)
                        log.info(f"[collect] copy_message OK, items={len(state_data['items'])}")
                        bot.send_message(
                            message.chat.id,
                            f"Ссылка подтверждена и принята ({len(state_data['items'])}). Перешлите еще или нажмите 'Готово'."
                        )
                        return
                    except Exception as e:
                        log.warning(f"[collect] copy_message failed: chat_id={from_chat_id} msg_id={msg_id} err={e}")
                        # Если копирование не удалось, и мы уверены в «нашей» группе — предупреждаем
                        if expected_id is not None and int(from_chat_id) != int(expected_id):
                            bot.send_message(
                                message.chat.id,
                                "Ссылка ведет не на нашу приватную группу. Пожалуйста, пришлите корректную ссылку."
                            )
                        else:
                            bot.send_message(
                                message.chat.id,
                                "Не удалось подтвердить ссылку. Убедитесь, что бот состоит в чате и ссылка корректна."
                            )
                        return

            if is_document and message.document.mime_type == 'text/csv':
                state_data['items'].append(message)
                log.info(f"[collect] CSV accepted, items={len(state_data['items'])}")
                bot.send_message(message.chat.id, f"CSV принят ({len(state_data['items'])}). Перешлите еще или нажмите 'Готово'.")
                return

            if is_poll:
                log.info("[collect] poll rejected (need link)")
                bot.send_message(message.chat.id, "Пожалуйста, пришлите ссылку на этот опрос (t.me/...), обычные пересылки и прямые опросы не принимаются.")
                return

            if message.content_type == 'text':
                bot.send_message(message.chat.id, "Пришлите, пожалуйста, ссылку на сообщение (t.me/...) из приватной группы Совета или CSV-файл.")
            return

        # --- 以降、質疑応答フロー ---
        if state == 'awaiting_vote_response':
            appeal = appealManager.get_appeal(case_id)
            if not appeal:
                log.warning(f"[flow] appeal not found case_id={case_id}")
                return
            if message.content_type == 'text' and message.text.strip().lower().startswith("да"):
                expected_responses = (appeal.get('total_voters') or 1) - 1
                appealManager.update_appeal(case_id, 'expected_responses', expected_responses)
                user_states[user_id]['state'] = 'awaiting_main_argument'
                log.info(f"[flow] vote YES case_id={case_id} expected_responses={expected_responses}")
                bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            elif message.content_type == 'text' and message.text.strip().lower().startswith("нет"):
                log.info(f"[flow] vote NO case_id={case_id}")
                bot.send_message(message.chat.id, "Согласно правилам, все участники должны принимать участие в голосовании. Ваша заявка отклонена.", reply_markup=types.ReplyKeyboardRemove())
                appealManager.delete_appeal(case_id)
                user_states.pop(user_id, None)
            else:
                bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа.")

        elif state == 'awaiting_main_argument':
            log.info(f"[flow] main_argument case_id={case_id} len={len(message.text or '')}")
            appealManager.update_appeal(case_id, 'applicant_arguments', message.text)
            user_states[user_id]['state'] = 'awaiting_q1'
            bot.send_message(message.chat.id, "Спасибо. Теперь ответьте, пожалуйста, на несколько уточняющих вопросов.")
            bot.send_message(message.chat.id, "Вопрос 1/3: Какой конкретно пункт устава, по вашему мнению, был нарушен?")

        elif state == 'awaiting_q1':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q1'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            log.info(f"[flow] q1 saved case_id={case_id}")
            user_states[user_id]['state'] = 'awaiting_q2'
            bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")

        elif state == 'awaiting_q2':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q2'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            log.info(f"[flow] q2 saved case_id={case_id}")
            user_states[user_id]['state'] = 'awaiting_q3'
            bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")

        elif state == 'awaiting_q3':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q3'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states.pop(user_id, None)  # Завершаем диалог с заявителем
            log.info(f"[flow] q3 saved; dialog closed case_id={case_id}")
            request_counter_arguments(bot, case_id)