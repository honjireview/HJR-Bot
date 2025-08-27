# app/repositories/appeal_repo.py
# -*- coding: utf-8 -*-
import json
import logging
import psycopg
from thefuzz import fuzz
from app.repositories import state_repo
from app.core.db import get_connection

log = logging.getLogger("hjr-bot.repo.appeal")

def create(case_id, initial_data):
    """Создает новую апелляцию в БД."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            applicant_info_json = json.dumps(initial_data.get('applicant_info', {}))
            cur.execute(
                """
                INSERT INTO appeals (case_id, applicant_chat_id, decision_text, status, created_at, applicant_info, total_voters, message_thread_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (case_id, initial_data.get('applicant_chat_id'), initial_data.get('decision_text'),
                 initial_data.get('status'), initial_data.get('created_at'),
                 applicant_info_json, initial_data.get('total_voters'), initial_data.get('message_thread_id'))
            )
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось создать апелляцию #{case_id}: {e}")


def get_by_id(case_id):
    """Получает апелляцию по ID."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE case_id = %s", (case_id,))
            record = cur.fetchone()
            if record:
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, record))
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось получить дело #{case_id}: {e}")
    return None

def update(case_id, key, value):
    """Обновляет поле в апелляции."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            query = psycopg.sql.SQL("UPDATE appeals SET {key} = %s WHERE case_id = %s").format(
                key=psycopg.sql.Identifier(key)
            )
            cur.execute(query, (value, case_id))
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось обновить дело #{case_id} (поле {key}): {e}")

def delete(case_id):
    """Удаляет апелляцию из БД."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM appeals WHERE case_id = %s", (case_id,))
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось удалить дело #{case_id}: {e}")


def get_pending_appeals():
    """Возвращает все апелляции в статусе 'collecting' или 'reviewing'."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE status IN ('collecting', 'reviewing', 'review_poll_pending')")
            records = cur.fetchall()
            if not records: return []
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, record)) for record in records]
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось получить активные апелляции: {e}")
    return []

def get_active_appeal_by_user(user_id):
    """Находит активную (не закрытую) апелляцию от конкретного пользователя."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id FROM appeals WHERE (applicant_info->>'id')::bigint = %s AND status NOT IN ('closed', 'closed_after_review', 'closed_invalid')",
                (user_id,)
            )
            record = cur.fetchone()
            return record[0] if record else None
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось проверить активные апелляции для user_id {user_id}: {e}")
    return None

def find_similar(decision_text: str, similarity_threshold=90):
    """Ищет в базе апелляции с похожим предметом спора."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT case_id, decision_text FROM appeals")
            records = cur.fetchall()
            for record in records:
                case_id, db_text = record
                if not db_text: continue
                similarity = fuzz.ratio(decision_text, db_text)
                if similarity >= similarity_threshold:
                    log.info(f"Найдена похожая апелляция: #{case_id} (схожесть: {similarity}%)")
                    return {"case_id": case_id, "similarity": similarity}
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось найти похожие апелляции: {e}")
    return None