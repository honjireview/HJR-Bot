# app/services/timer_service.py
# -*- coding: utf-8 -*-
import logging
import time
from datetime import datetime, timedelta
from threading import Thread

# ИСПРАВЛЕНО
from ..core.config import COMMIT_HASH, BOT_VERSION, EDITORS_GROUP_ID
from ..repositories import appeal_repo, editor_repo
from . import appeal_service

log = logging.getLogger("hjr-bot.service.timer")

def _check_appeals(bot):
    """Основная функция проверки, запускаемая в цикле."""
    try:
        active_appeals = appeal_repo.get_pending_appeals()
        if not active_appeals:
            return

        for appeal in active_appeals:
            case_id = appeal['case_id']
            status = appeal.get('status')
            expires_at = appeal.get('timer_expires_at')

            if not expires_at:
                continue

            # Устанавливаем таймзону для сравнения
            now = datetime.now(expires_at.tzinfo)

            # --- Проверка 1: Таймер истек ---
            if now > expires_at:
                if status == 'collecting':
                    log.info(f"Таймер сбора контраргументов для дела #{case_id} истек.")
                    appeal_service.finalize_appeal(appeal, bot, COMMIT_HASH, BOT_VERSION)

                elif status == 'review_poll_pending':
                    log.info(f"Таймер голосования по пересмотру дела #{case_id} истек.")
                    _handle_review_poll_end(bot, appeal)

                elif status == 'reviewing':
                    log.info(f"Таймер сбора аргументов для пересмотра дела #{case_id} истек.")
                    appeal_service.finalize_review(appeal, bot, COMMIT_HASH, BOT_VERSION)
                continue

            # --- Проверка 2: Досрочное завершение сбора контраргументов ---
            if status == 'collecting':
                expected = appeal.get('expected_responses')
                if expected is not None and expected > 0:
                    council_answers = appeal.get('council_answers') or []
                    if len(council_answers) >= expected:
                        log.info(f"Досрочное завершение для дела #{case_id}: все контраргументы собраны.")
                        appeal_service.finalize_appeal(appeal, bot, COMMIT_HASH, BOT_VERSION)

    except Exception as e:
        log.error(f"Критическая ошибка в цикле проверки таймеров: {e}", exc_info=True)


def _handle_review_poll_end(bot, appeal: dict):
    """Обрабатывает завершение голосования о пересмотре."""
    case_id = appeal['case_id']
    review_data = appeal.get('review_data', {})
    poll_message_id = review_data.get('poll_message_id')
    thread_id = appeal.get("message_thread_id")

    if not (poll_message_id and EDITORS_GROUP_ID):
        log.error(f"Невозможно остановить опрос по делу #{case_id}: отсутствуют poll_message_id или EDITORS_GROUP_ID.")
        appeal_repo.update(case_id, "status", "closed")
        return

    try:
        final_poll = bot.stop_poll(EDITORS_GROUP_ID, poll_message_id)

        total_members = bot.get_chat_member_count(EDITORS_GROUP_ID) - 1
        inactive_members = editor_repo.count_inactive()
        active_members = total_members - inactive_members
        threshold = active_members / 2

        for_votes = 0
        for opt in final_poll.options:
            if "да" in opt.text.lower():
                for_votes = opt.voter_count

        review_data['poll'] = {
            "question": final_poll.question,
            "options": [{"text": o.text, "voter_count": o.voter_count} for o in final_poll.options]
        }
        appeal_repo.update(case_id, "review_data", review_data)

        if for_votes > threshold:
            log.info(f"Пересмотр дела #{case_id} одобрен ({for_votes} > {threshold}).")
            appeal_repo.update(case_id, "status", "reviewing")
            new_expires_at = datetime.utcnow() + timedelta(hours=24)
            appeal_repo.update(case_id, "timer_expires_at", new_expires_at)
            bot.send_message(
                EDITORS_GROUP_ID,
                f"📣 Пересмотр дела №{case_id} одобрен. Начался 24-часовой сбор доп. аргументов через `/replyrecase {case_id}` в ЛС.",
                message_thread_id=thread_id
            )
        else:
            log.info(f"Пересмотр дела #{case_id} отклонен ({for_votes} <= {threshold}).")
            appeal_repo.update(case_id, "status", "closed")
            bot.send_message(
                EDITORS_GROUP_ID,
                f"Пересмотр дела №{case_id} не набрал большинства голосов и был отклонен.",
                message_thread_id=thread_id
            )

    except Exception as e:
        log.error(f"Ошибка при остановке или анализе опроса по делу #{case_id}: {e}")
        appeal_repo.update(case_id, "status", "closed")
        bot.send_message(EDITORS_GROUP_ID, f"Произошла ошибка при завершении голосования по делу #{case_id}. Пересмотр отменен.", message_thread_id=thread_id)


def start_timer_check(bot):
    """Запускает бесконечный цикл проверки таймеров в отдельном потоке."""
    log.info("Запущена фоновая задача проверки таймеров.")

    def timer_loop():
        while True:
            _check_appeals(bot)
            time.sleep(60)

    thread = Thread(target=timer_loop, daemon=True)
    thread.start()