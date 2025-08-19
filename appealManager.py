# -*- coding: utf-8 -*-

import os
import json
import psycopg
from datetime import datetime
from telebot import types

import connectionChecker
from handlers.council_helpers import resolve_council_id

def _get_conn():
    # ... (код без изменений)
    conn = connectionChecker.db_conn
    if conn is None or conn.closed:
        if connectionChecker.check_db_connection():
            conn = connectionChecker.db_conn
        else:
            raise RuntimeError("Не удалось восстановить соединение с БД.")
    return conn

def create_appeal(case_id, initial_data):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            applicant_info_json = json.dumps(initial_data.get('applicant_info', {}))
            cur.execute(
                """
                INSERT INTO appeals (case_id, applicant_chat_id, decision_text, status, created_at, applicant_info, total_voters)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO UPDATE SET
                    applicant_chat_id = EXCLUDED.applicant_chat_id,
                                                 decision_text = EXCLUDED.decision_text,
                                                 status = EXCLUDED.status,
                                                 created_at = EXCLUDED.created_at,
                                                 applicant_info = EXCLUDED.applicant_info;
                """,
                (case_id, initial_data.get('applicant_chat_id'), initial_data.get('decision_text'),
                 initial_data.get('status'), initial_data.get('created_at'),
                 applicant_info_json, initial_data.get('total_voters'))
            )
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось создать апелляцию #{case_id}: {e}")

def get_appeal(case_id):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE case_id = %s", (case_id,))
            record = cur.fetchone()
            if record:
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, record))
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить дело #{case_id}: {e}")
    return None

def update_appeal(case_id, key, value):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            query = psycopg.sql.SQL("UPDATE appeals SET {key} = %s WHERE case_id = %s").format(
                key=psycopg.sql.Identifier(key)
            )
            cur.execute(query, (value, case_id))
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось обновить дело #{case_id} (поле {key}): {e}")

def add_council_answer(case_id, answer_data):
    # ... (код без изменений)
    try:
        appeal = get_appeal(case_id)
        if appeal:
            current_answers = appeal.get('council_answers') or []
            current_answers.append(answer_data)
            update_appeal(case_id, 'council_answers', current_answers)
    except Exception as e:
        print(f"[ОШИБКА] Не удалось добавить ответ в дело #{case_id}: {e}")

def delete_appeal(case_id):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM appeals WHERE case_id = %s", (case_id,))
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось удалить дело #{case_id}: {e}")

def get_expired_appeals():
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE status = 'collecting' AND timer_expires_at IS NOT NULL AND timer_expires_at < NOW() AT TIME ZONE 'utc'")
            records = cur.fetchall()
            if not records: return []
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, record)) for record in records]
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить просроченные апелляции: {e}")
    return []

def get_active_appeal_by_user(user_id):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id FROM appeals WHERE (applicant_info->>'id')::bigint = %s AND status != 'closed'",
                (user_id,)
            )
            record = cur.fetchone()
            return record[0] if record else None
    except Exception as e:
        print(f"[ОШИБКА] Не удалось проверить активные апелляции для user_id {user_id}: {e}")
    return None

def get_user_state(user_id):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT state, data FROM user_states WHERE user_id = %s", (user_id,))
            record = cur.fetchone()
            if record:
                return {"state": record[0], "data": record[1] or {}}
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить состояние для user_id {user_id}: {e}")
    return None

def set_user_state(user_id, state, data=None):
    # ... (код без изменений)
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
        print(f"[ОШИБКА] Не удалось установить состояние для user_id {user_id}: {e}")

def delete_user_state(user_id):
    # ... (код без изменений)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_states WHERE user_id = %s", (user_id,))
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось удалить состояние для user_id {user_id}: {e}")

# --- НОВАЯ ВЕРСИЯ: Проверка членства в реальном времени ---
def is_user_an_editor(bot, user_id):
    """Проверяет, является ли пользователь участником чата редакторов."""
    chat_id = resolve_council_id()
    if not chat_id:
        print("[WARN] ID чата редакторов не настроен, авторизация невозможна.")
        return False
    try:
        member = bot.get_chat_member(chat_id, user_id)
        # Участником считается любой, кроме тех, кто вышел или был забанен
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        # Если API возвращает ошибку (например, "user not found"), значит, он не участник
        print(f"[AUTH] Ошибка при проверке членства для user_id {user_id}: {e}")
        return False

# --- ИЗМЕНЕНИЕ: Функция теперь возвращает ID лога ---
def log_interaction(user_id, action, case_id=None, details=""):
    """Записывает действие в лог и возвращает ID этой записи."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            db_user_id = user_id if user_id != "SYSTEM" else None

            cur.execute(
                """
                INSERT INTO interaction_logs (user_id, case_id, action, details)
                VALUES (%s, %s, %s, %s) RETURNING log_id;
                """,
                (db_user_id, case_id, action, details)
            )
            log_id = cur.fetchone()[0]
            conn.commit()
            return log_id
    except Exception as e:
        print(f"[ОШИБКА] Не удалось записать лог для user_id {user_id}: {e}")
    return None