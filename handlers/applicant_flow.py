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

EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID')
COUNCIL_CHAT_ID = EDITORS_CHANNEL_ID
_RESOLVED_COUNCIL_ID = {'value': None}

log = logging.getLogger("hjr-bot")


def register_applicant_handlers(bot, user_states):
    """
    Регистрирует обработчики для процесса подачи апелляции.
    """

    def _resolve_council_chat_id():
        """
        Попытка один раз резолвить значение из окружения в удобный формат:
        - int (например -1002063604198) для приватных/каналов
        - строка с @ для публичных каналов (например '@somechannel')
        - None если не задано
        """
        if _RESOLVED_COUNCIL_ID['value'] is not None:
            return _RESOLVED_COUNCIL_ID['value']
        raw = (COUNCIL_CHAT_ID or "").strip()
        if not raw:
            log.warning("[council-id] EDITORS_CHANNEL_ID пуст. Строгая проверка отключена.")
            return None
        # если это просто число (без -100), превратим в -100...
        if re.fullmatch(r'\d+', raw):
            try:
                val = int(raw)
                resolved = val if val < 0 else int(f"-100{val}")
                _RESOLVED_COUNCIL_ID['value'] = resolved
                log.info(f"[council-id] resolved numeric to {resolved}")
                return resolved
            except Exception:
                pass
        # если уже '-100...' или '-123...' — int
        if re.fullmatch(r'-?\d+', raw):
            try:
                resolved = int(raw)
                _RESOLVED_COUNCIL_ID['value'] = resolved
                log.info(f"[council-id] resolved to int {resolved}")
                return resolved
            except Exception:
                pass
        # если начинается с @ — используем как имя канала
        if raw.startswith('@'):
            _RESOLVED_COUNCIL_ID['value'] = raw
            log.info(f"[council-id] resolved to username {raw}")
            return raw
        # попытка добавить @ если это имя без @
        if re.fullmatch(r'[A-Za-z0-9_]{5,}', raw):
            resolved = f"@{raw}"
            _RESOLVED_COUNCIL_ID['value'] = resolved
            log.info(f"[council-id] resolved to username @{raw}")
            return resolved

        log.error(f"[council-id] Невозможно распознать EDITORS_CHANNEL_ID='{raw}'")
        return None

    def _is_link_from_council(from_chat_id):
        """
        Проверяет, что распарсенная ссылочная цель совпадает с каналом/чатом Совета.
        Если EDITORS_CHANNEL_ID не задан — возвращает True (позволяет любые ссылки),
        иначе требует точного соответствия:
          - если целевой id int (например -100...) — сравниваем как int
          - если целевой username (строка с @) — сравниваем строково
        """
        resolved = _resolve_council_chat_id()
        if not resolved:
            # если не задано — не принуждаем проверку
            return True
        try:
            # нормализуем from_chat_id к типу целевого resolved
            if isinstance(resolved, int):
                # from_chat_id может быть строкой '@username' для публичных — в таком случае не совпадёт
                return int(from_chat_id) == resolved
            else:
                # resolved — строка '@username'
                return str(from_chat_id).lower() == str(resolved).lower()
        except Exception:
            return False

    def _set_council_chat_id_runtime(chat_id: int):
        _RESOLVED_COUNCIL_ID['value'] = int(chat_id)
        log.warning(f"[council-id] Runtime override установлен: {chat_id}")

    def _parse_message_link(text: str):
        """
        Поддерживает форматы:
          - https://t.me/c/2063604198/3087/7972  (берёт последний числовой сегмент как message_id)
          - https://t.me/username/3087
          - t.me/username/3087
          - @username 3087
        Возвращает (from_chat_id, message_id) где from_chat_id — int (для приватных internal id -> -100<id>)
        или строка '@username' для публичных каналов/профилей, либо None.
        """
        s = (text or "").strip()
        if not s:
            return None

        # Уберём протокол и параметры
        s_clean = re.sub(r'^https?://', '', s, flags=re.IGNORECASE).split('?', 1)[0].split('#', 1)[0]

        # приватные чаты/каналы: t.me/c/<internal>/<...>/<message_id>
        if '/c/' in s_clean:
            nums = re.findall(r'/([0-9]+)', s_clean)
            if len(nums) >= 2:
                try:
                    chat_internal_id = nums[0]
                    msg_id = nums[-1]
                    from_chat_id = int(f"-100{chat_internal_id}")
                    return from_chat_id, int(msg_id)
                except Exception:
                    return None

        # публичный канал/профиль: t.me/<username>/<...>/<message_id>
        m = re.search(r'^(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})(?:/|$)', s_clean, flags=re.IGNORECASE)
        if m:
            username = m.group(1)
            nums = re.findall(r'/([0-9]+)', s_clean)
            if nums:
                try:
                    msg_id = int(nums[-1])
                    return f"@{username}", msg_id
                except Exception:
                    return None
            return None

        # возможные варианты: '@channel 1234' или '@channel/1234' или 'channel 1234'
        m2 = re.search(r'@([A-Za-z0-9_]{5,})', s_clean)
        nums2 = re.findall(r'([0-9]{3,})', s_clean)
        if m2 and nums2:
            try:
                return f"@{m2.group(1)}", int(nums2[-1])
            except Exception:
                return None

        return None

    @bot.message_handler(commands=['start'])
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

    @bot.message_handler(commands=['cancel'])
    def cancel_process(message):
        user_id = message.from_user.id
        state = user_states.pop(user_id, None)
        if state and 'case_id' in state:
            try:
                appealManager.delete_appeal(state['case_id'])
            except Exception:
                log.exception(f"[cancel] не удалось удалить апелляцию {state.get('case_id')}")
        bot.send_message(message.chat.id, "Процесс подачи апелляции отменен.", reply_markup=types.ReplyKeyboardRemove())

    @bot.callback_query_handler(func=lambda call: call.data == "start_appeal")
    def handle_start_appeal_callback(call):
        user_id = call.from_user.id
        user_states[user_id] = {'state': 'collecting_items', 'items': []}
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
            "Пожалуйста, пришлите ссылки на сообщения (t.me/...) из приватной группы Совета, которые вы хотите оспорить. Когда закончите, нажмите 'Готово'.",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "done_collecting")
    def handle_done_collecting_callback(call):
        user_id = call.from_user.id
        state_data = user_states.get(user_id)
        if not state_data or not state_data.get('items'):
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
        for item in state_data['items']:
            poll = getattr(item, 'poll', None)
            text = getattr(item, 'text', None)
            if poll:
                poll_count += 1
                total_voters = getattr(poll, 'total_voter_count', total_voters)
                options_text = "\n".join([f"- {opt.text}: {getattr(opt, 'voter_count', 0)} голосов" for opt in poll.options])
                full_decision_text += f"\n\n--- Опрос ---\nВопрос: {poll.question}\n{options_text}"
            elif text:
                full_decision_text += f"\n\n--- Сообщение ---\n{text}"
            else:
                # Пытаемся извлечь из dict-like
                try:
                    if isinstance(item, dict):
                        if 'poll' in item:
                            p = item['poll']
                            poll_count += 1
                            total_voters = p.get('total_voter_count', total_voters)
                            options_text = "\n".join([f"- {opt.get('text','')}: {opt.get('voter_count',0)} голосов" for opt in p.get('options',[])])
                            full_decision_text += f"\n\n--- Опрос ---\nВопрос: {p.get('question','')}\n{options_text}"
                        if 'text' in item:
                            full_decision_text += f"\n\n--- Сообщение ---\n{item.get('text','')}"
                except Exception:
                    pass

        if poll_count > 1:
            bot.send_message(message.chat.id, "Ошибка: Вы можете оспорить только одно голосование за раз. Начните заново: /start")
            user_states.pop(user_id, None)
            return

        case_id = random.randint(10000, 99999)
        user_states[user_id]['case_id'] = case_id
        initial_data = {
            'applicant_chat_id': message.chat.id,
            'decision_text': full_decision_text.strip(),
            'total_voters': total_voters,
            'status': 'collecting'
        }
        try:
            appealManager.create_appeal(case_id, initial_data)
            log.info(f"Дело #{case_id} успешно создано/обновлено.")
        except Exception:
            log.exception(f"[appeal-create] не удалось создать/обновить дело #{case_id}")

        bot.send_message(message.chat.id, f"Все объекты приняты. Вашему делу присвоен номер #{case_id}.")

        if poll_count == 1:
            user_states[user_id]['state'] = 'awaiting_vote_response'
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("Да, я голосовал(а)"), types.KeyboardButton("Нет, я не голосовал(а)"))
            bot.send_message(message.chat.id, "Уточняющий вопрос: вы принимали участие в этом голосовании?", reply_markup=markup)
        else:
            user_states[user_id]['state'] = 'awaiting_main_argument'
            bot.send_message(message.chat.id, "Теперь, пожалуйста, изложите ваши основные аргументы.")

    def request_counter_arguments(bot, case_id):
        appeal = appealManager.get_appeal(case_id)
        if not appeal:
            log.warning(f"[request] апелляция #{case_id} не найдена")
            return

        # Составляем информативный текст
        decision_text = appeal.get('decision_text') or "(текст решения отсутствует)"
        applicant_args = appeal.get('applicant_arguments') or "(аргументы заявителя не указаны)"
        answers = appeal.get('applicant_answers') or {}
        q1 = answers.get('q1', '(нет ответа)')
        q2 = answers.get('q2', '(нет ответа)')
        q3 = answers.get('q3', '(нет ответа)')

        request_text = (
            f"📣 *Запрос контраргументов по апелляции №{case_id}* 📣\n\n"
            f"*Решение / содержимое спора:*\n{decision_text}\n\n"
            f"*Аргументы заявителя:*\n{applicant_args}\n\n"
            f"*Уточняющие ответы заявителя:*\n"
            f"1) {q1}\n"
            f"2) {q2}\n"
            f"3) {q3}\n\n"
            f"Пожалуйста, присылайте ваши контраргументы в течение 24 часов. (апелляция #{case_id})"
        )

        target = _resolve_council_chat_id()
        if not target:
            log.error(f"[request] Не задан EDITORS_CHANNEL_ID — не могу отправить запрос для дела #{case_id}")
            return

        # Приведём строковые числовые id к int (Telegram API принимает int для chat_id)
        if isinstance(target, str) and re.fullmatch(r'-?\d+', target):
            try:
                target = int(target)
            except Exception:
                pass

        try:
            # Пробуем отправить с Markdown
            bot.send_message(target, request_text, parse_mode="Markdown")
            log.info(f"[request] Отправлен запрос контраргументов для дела #{case_id} в {target}")
        except Exception as e:
            log.exception(f"[request] Ошибка отправки в {target}: {e}. Попытка без parse_mode.")
            try:
                bot.send_message(target, request_text)
                log.info(f"[request] Повторная отправка без parse_mode успешна для дела #{case_id}")
            except Exception as e2:
                log.exception(f"[request] Повторная отправка также упала: {e2}")

        expires_at = datetime.utcnow() + timedelta(hours=24)
        try:
            appealManager.update_appeal(case_id, 'timer_expires_at', expires_at)
            log.info(f"Таймер для дела #{case_id} установлен на {expires_at.isoformat()}")
        except Exception:
            log.exception(f"[request] не удалось обновить таймер для дела #{case_id}")

    @bot.message_handler(
        func=lambda message: str(user_states.get(message.from_user.id, {}).get('state', '')).startswith('awaiting_')
                             or user_states.get(message.from_user.id, {}).get('state') == 'collecting_items',
        content_types=['text', 'document']
    )
    def handle_dialogue_messages(message):
        user_id = message.from_user.id
        state_data = user_states.get(user_id)
        if not state_data:
            return

        state = state_data.get('state')
        case_id = state_data.get('case_id')

        if state == 'collecting_items':
            if message.content_type == 'text':
                parsed = _parse_message_link(message.text)
                if parsed:
                    from_chat_id, msg_id = parsed
                    log.info(f"[collect] parsed from_chat_id={from_chat_id} msg_id={msg_id}")

                    # Проверяем, что ссылка из нужного чата/канала (если EDITORS_CHANNEL_ID задан)
                    if not _is_link_from_council(from_chat_id):
                        bot.send_message(
                            message.chat.id,
                            "Ссылка должна вести на сообщение из приватной группы/канала Совета. Пожалуйста, пришлите ссылку из правильного места."
                        )
                        return

                    # Проверка доступа к чату до копирования
                    try:
                        bot.get_chat(from_chat_id)
                    except Exception as e_gc:
                        log.warning(f"[collect] get_chat failed for {from_chat_id}: {e_gc}")
                        bot.send_message(
                            message.chat.id,
                            "Не удалось получить сообщение по ссылке. Пожалуйста, добавьте бота (@hjrmainbot) в приватную группу/канал, "
                            "чтобы он мог получить сообщение, и попробуйте снова. Если это публичный канал, убедитесь, что ссылка корректна."
                        )
                        return

                    # Попытка copy_message, fallback на forward_message
                    try:
                        copied = bot.copy_message(chat_id=message.chat.id, from_chat_id=from_chat_id, message_id=msg_id)
                        try:
                            bot.delete_message(chat_id=message.chat.id, message_id=copied.message_id)
                        except Exception:
                            pass

                        state_data['items'].append(copied)
                        log.info(f"[collect] accepted (copied), items={len(state_data['items'])}")
                        bot.send_message(message.chat.id, f"Ссылка подтверждена и принята ({len(state_data['items'])}).")
                        return
                    except Exception as e_copy:
                        log.warning(f"[collect] copy_message failed: {e_copy}. Попытка forward_message как fallback.")
                        try:
                            forwarded = bot.forward_message(chat_id=message.chat.id, from_chat_id=from_chat_id, message_id=msg_id)
                            try:
                                bot.delete_message(chat_id=message.chat.id, message_id=forwarded.message_id)
                            except Exception:
                                pass
                            state_data['items'].append(forwarded)
                            log.info(f"[collect] accepted (forwarded), items={len(state_data['items'])}")
                            bot.send_message(message.chat.id, f"Ссылка подтверждена и принята ({len(state_data['items'])}).")
                            return
                        except Exception as e_forw:
                            log.warning(f"[collect] forward_message failed: {e_forw}")
                            bot.send_message(
                                message.chat.id,
                                "Не удалось получить сообщение по ссылке. Убедитесь, что:\n"
                                "- вы дали боту доступ к этой группе/каналу (добавьте @hjrmainbot),\n"
                                "- ссылка корректна (t.me/... ), и\n"
                                "- сообщение с таким id существует.\n\nПосле добавления бота повторите попытку."
                            )
                            return

            # Если дошли сюда — не распознана ссылка
            bot.send_message(message.chat.id, "Пришлите, пожалуйста, ссылку на сообщение (t.me/...), только из приватной группы/канала Совета.")
            return

        elif state == 'awaiting_vote_response':
            appeal = appealManager.get_appeal(case_id)
            if not appeal:
                bot.send_message(message.chat.id, "Ошибка: дело не найдено.")
                user_states.pop(user_id, None)
                return
            text = (message.text or "").strip()
            if text.startswith("Да"):
                expected_responses = (appeal.get('total_voters') or 1) - 1
                appealManager.update_appeal(case_id, 'expected_responses', expected_responses)
                user_states[user_id]['state'] = 'awaiting_main_argument'
                bot.send_message(message.chat.id, "Понятно. Теперь, пожалуйста, изложите ваши основные аргументы.", reply_markup=types.ReplyKeyboardRemove())
            elif text.startswith("Нет"):
                bot.send_message(message.chat.id, "Согласно правилам, все участники должны принимать участие в голосовании. Ваша апелляция отклонена.")
                appealManager.delete_appeal(case_id)
                user_states.pop(user_id, None)
            else:
                bot.send_message(message.chat.id, "Пожалуйста, используйте кнопки для ответа.")

        elif state == 'awaiting_main_argument':
            appealManager.update_appeal(case_id, 'applicant_arguments', message.text)
            user_states[user_id]['state'] = 'awaiting_q1'
            bot.send_message(message.chat.id, "Спасибо. Теперь ответьте на уточняющие вопросы.")
            bot.send_message(message.chat.id, "Вопрос 1/3: Какой пункт устава, по вашему мнению, был нарушен?")

        elif state == 'awaiting_q1':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q1'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states[user_id]['state'] = 'awaiting_q2'
            bot.send_message(message.chat.id, "Вопрос 2/3: Какой результат вы считаете справедливым?")

        elif state == 'awaiting_q2':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q2'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states[user_id]['state'] = 'awaiting_q3'
            bot.send_message(message.chat.id, "Вопрос 3/3: Есть ли дополнительный контекст, важный для дела?")

        elif state == 'awaiting_q3':
            appeal = appealManager.get_appeal(case_id)
            if appeal:
                current_answers = appeal.get('applicant_answers', {}) or {}
                current_answers['q3'] = message.text
                appealManager.update_appeal(case_id, 'applicant_answers', current_answers)
            user_states.pop(user_id, None)
            log.info(f"[flow] q3 saved; dialog closed case_id={case_id}")
            request_counter_arguments(bot, case_id)