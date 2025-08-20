# -*- coding: utf-8 -*-

import os
import json
import psycopg
import logging
from datetime import datetime
# ИСПРАВЛЕНО: Добавлен недостающий импорт, который вызывал ошибку
from thefuzz import fuzz

import connectionChecker

log = logging.getLogger("hjr-bot.appeal_manager")

def are_arguments_meaningful(text: str, min_length: int = 20) -> bool:
    # ... (код без изменений) ...
    if not text:
        return False
    text = text.strip().lower()
    if text == 'тест':
        return False
    if len(text) < min_length:
        return False
    return True

def find_similar_appeal(decision_text: str, similarity_threshold=90):
    """Ищет в базе апелляции с похожим предметом спора, используя fuzz.ratio."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT case_id, decision_text FROM appeals")
            records = cur.fetchall()

            for record in records:
                case_id, db_text = record
                if not db_text: continue # Пропускаем, если текст пустой
                similarity = fuzz.ratio(decision_text, db_text)
                if similarity >= similarity_threshold:
                    log.info(f"Найдена похожая апелляция: #{case_id} (схожесть: {similarity}%)")
                    return {"case_id": case_id, "similarity": similarity}
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось найти похожие апелляции: {e}")
    return None

# ... (остальной код файла без изменений) ...
def _get_conn():
    conn = connectionChecker.db_conn
    if conn is None or conn.closed:
        if connectionChecker.check_db_connection():
            conn = connectionChecker.db_conn
        else:
            raise RuntimeError("Не удалось восстановить соединение с БД.")
    return conn

def create_appeal(case_id, initial_data):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            applicant_info_json = json.dumps(initial_data.get('applicant_info', {}))
            cur.execute(
                """
                INSERT INTO appeals (case_id, applicant_chat_id, decision_text, status, created_at, applicant_info, total_voters, message_thread_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO UPDATE SET
                    applicant_chat_id = EXCLUDED.applicant_chat_id, decision_text = EXCLUDED.decision_text,
                                                 status = EXCLUDED.status, created_at = EXCLUDED.created_at,
                                                 applicant_info = EXCLUDED.applicant_info, message_thread_id = EXCLUDED.message_thread_id;
                """,
                (case_id, initial_data.get('applicant_chat_id'), initial_data.get('decision_text'),
                 initial_data.get('status'), initial_data.get('created_at'),
                 applicant_info_json, initial_data.get('total_voters'), initial_data.get('message_thread_id'))
            )
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось создать апелляцию #{case_id}: {e}")

def get_appeal(case_id):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE case_id = %s", (case_id,))
            record = cur.fetchone()
            if record:
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, record))
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось получить дело #{case_id}: {e}")
    return None

def update_appeal(case_id, key, value):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)

            # Используем psycopg.sql для безопасной вставки имен колонок
            query = psycopg.sql.SQL("UPDATE appeals SET {key} = %s WHERE case_id = %s").format(
                key=psycopg.sql.Identifier(key)
            )
            cur.execute(query, (value, case_id))
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось обновить дело #{case_id} (поле {key}): {e}")

def add_council_answer(case_id, answer_data):
    try:
        appeal = get_appeal(case_id)
        if appeal:
            current_answers = appeal.get('council_answers') or []
            current_answers.append(answer_data)
            update_appeal(case_id, 'council_answers', current_answers)
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось добавить ответ в дело #{case_id}: {e}")

def delete_appeal(case_id):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM appeals WHERE case_id = %s", (case_id,))
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось удалить дело #{case_id}: {e}")

def get_appeals_in_collection():
    """Возвращает все апелляции, которые сейчас в стадии сбора контраргументов."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE status IN ('collecting', 'reviewing')")
            records = cur.fetchall()
            if not records: return []
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, record)) for record in records]
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось получить активные апелляции: {e}")
    return []

def get_active_appeal_by_user(user_id):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id FROM appeals WHERE (applicant_info->>'id')::bigint = %s AND status != 'closed' AND status != 'closed_after_review'",
                (user_id,)
            )
            record = cur.fetchone()
            return record[0] if record else None
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось проверить активные апелляции для user_id {user_id}: {e}")
    return None

def get_user_state(user_id):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT state, data FROM user_states WHERE user_id = %s", (user_id,))
            record = cur.fetchone()
            if record:
                return {"state": record[0], "data": record[1] or {}}
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось получить состояние для user_id {user_id}: {e}")
    return None

def set_user_state(user_id, state, data=None):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            data_json = json.dumps(data or {})
            cur.execute(
                """
                INSERT INTO user_states (user_id, state, data)
                VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                    state = EXCLUDED.state, data = EXCLUDED.data, updated_at = NOW();
                """,
                (user_id, state, data_json)
            )
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось установить состояние для user_id {user_id}: {e}")

def delete_user_state(user_id):
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_states WHERE user_id = %s", (user_id,))
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось удалить состояние для user_id {user_id}: {e}")

def update_editor_list(editors):
    """Полностью перезаписывает список редакторов в БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE editors;")
            if not editors:
                log.warning("Список редакторов для обновления пуст.")
                return

            editor_data = []
            for editor in editors:
                editor_data.append((editor.user.id, editor.user.username, editor.user.first_name))

            with cur.copy("COPY editors (user_id, username, first_name) FROM STDIN") as copy:
                for record in editor_data:
                    copy.write_row(record)
        conn.commit()
        log.info(f"Список редакторов обновлен. Загружено {len(editors)} пользователей.")
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось обновить список редакторов: {e}")

def is_user_an_editor(bot, user_id, chat_id):
    """Проверяет, является ли пользователь участником указанного чата."""
    log.info(f"--- [AUTH_CHECK] Начало проверки для user_id: {user_id} в чате: {chat_id} ---")
    if not chat_id:
        log.error("[AUTH_CHECK] ПРОВАЛ: ID чата редакторов не определён.")
        return False
    try:
        member = bot.get_chat_member(chat_id, user_id)
        status = member.status
        is_member = status in ['creator', 'administrator', 'member']
        log.info(f"[AUTH_CHECK] Результат: Пользователь {user_id} имеет статус '{status}'. Является участником: {is_member}.")
        return is_member
    except Exception as e:
        log.error(f"[AUTH_CHECK] ПРОВАЛ: Ошибка при вызове get_chat_member для user_id {user_id}. Детали: {e}")
        return False

def log_interaction(user_id, action, case_id=None, details=""):
    """Записывает действие в лог и возвращает ID этой записи."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            db_user_id = user_id if user_id != "SYSTEM" else None
            cur.execute(
                "INSERT INTO interaction_logs (user_id, case_id, action, details) VALUES (%s, %s, %s, %s) RETURNING log_id;",
                (db_user_id, case_id, action, details)
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось записать лог для user_id {user_id}: {e}")
    return None