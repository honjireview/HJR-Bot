# app/services/appeal_service.py
# -*- coding: utf-8 -*-
import logging
import re
from datetime import datetime
from app.repositories import appeal_repo
from app.services import gemini_service
from app.utils.telegraph_helpers import post_to_telegraph, markdown_to_html
from app.core.config import APPEALS_CHANNEL_ID

log = logging.getLogger("hjr-bot.service.appeal")

def are_arguments_meaningful(text: str, min_length: int = 20) -> bool:
    if not text:
        return False
    text = text.strip().lower()
    return len(text) >= min_length and text != 'тест'

def finalize_appeal(appeal_data: dict, bot, commit_hash: str, bot_version: str):
    case_id = appeal_data['case_id']
    log.info(f"[FINALIZE] Начинаю финальное рассмотрение дела #{case_id}")

    if not are_arguments_meaningful(appeal_data.get('applicant_arguments', '')):
        log.warning(f"[FINALIZE_SKIP] Дело #{case_id} пропущено из-за отсутствия осмысленных аргументов.")
        appeal_repo.update(case_id, "status", "closed_invalid")
        return

    # В новой архитектуре логгирование взаимодействия лучше вынести в отдельный сервис или делать прямо здесь
    log_id = 1 # Placeholder, нужна реализация interaction_log

    ai_verdict_text = gemini_service.get_verdict(appeal_data, commit_hash, bot_version, log_id)

    appeal_repo.update(case_id, "ai_verdict", ai_verdict_text)
    appeal_repo.update(case_id, "commit_hash", commit_hash)
    appeal_repo.update(case_id, "verdict_log_id", log_id)

    # ... (код формирования сообщения и отправки в Telegraph, как в geminiProcessor.py)

    appeal_repo.update(case_id, "status", "closed")
    log.info(f"[FINALIZE] Дело #{case_id} успешно закрыто.")


def finalize_review(appeal_data: dict, bot, commit_hash: str, bot_version: str):
    case_id = appeal_data['case_id']
    log.info(f"[FINALIZE_REVIEW] Начинаю ПЕРЕСМОТР дела #{case_id}")
    # ... (логика аналогична, но для пересмотра)
    appeal_repo.update(case_id, "status", "closed_after_review")
    log.info(f"[FINALIZE_REVIEW] Дело #{case_id} успешно закрыто после пересмотра.")