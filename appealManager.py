# -*- coding: utf-8 -*-

import os
import json
import psycopg
from datetime import datetime

import connectionChecker

def _get_conn():
    """Возвращает текущее соединение из connectionChecker."""
    conn = connectionChecker.db_conn
    if conn is None or conn.closed:
        print("Соединение с БД потеряно. Попытка переподключения...")
        if connectionChecker.check_db_connection():
            conn = connectionChecker.db_conn
        else:
            raise RuntimeError("Не удалось восстановить соединение с БД.")
    return conn

# --- Управление Апелляциями ---

def create_appeal(case_id, initial_data):
    """Создаёт новую запись об апелляции в БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            applicant_answers_json = json.dumps(initial_data.get('applicant_answers', {}))
            council_answers_json = json.dumps(initial_data.get('council_answers', []))

            cur.execute(
                """
                INSERT INTO appeals (case_id, applicant_chat_id, decision_text, applicant_arguments,
                                     applicant_answers, council_answers, voters_to_mention, total_voters, status,
                                     expected_responses, timer_expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO UPDATE SET
                    applicant_chat_id = EXCLUDED.applicant_chat_id,
                                                 decision_text = EXCLUDED.decision_text,
                                                 applicant_answers = EXCLUDED.applicant_answers,
                                                 council_answers = EXCLUDED.council_answers,
                                                 voters_to_mention = EXCLUDED.voters_to_mention,
                                                 total_voters = EXCLUDED.total_voters,
                                                 status = EXCLUDED.status,
                                                 expected_responses = EXCLUDED.expected_responses,
                                                 timer_expires_at = EXCLUDED.timer_expires_at;
                """,
                (case_id, initial_data['applicant_chat_id'], initial_data['decision_text'],
                 initial_data.get('applicant_arguments'), applicant_answers_json, council_answers_json,
                 initial_data.get('voters_to_mention', []), initial_data.get('total_voters'),
                 initial_data['status'], initial_data.get('expected_responses'),
                 initial_data.get('timer_expires_at'))
            )
        conn.commit()
        print(f"Дело #{case_id} успешно создано/обновлено.")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось создать апелляцию #{case_id}: {e}")

def get_appeal(case_id):
    """Возвращает данные по конкретному делу из БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE case_id = %s", (case_id,))
            record = cur.fetchone()
            if record:
                columns = [desc[0] for desc in cur.description]
                appeal_data = dict(zip(columns, record))
                return appeal_data
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить дело #{case_id}: {e}")
    return None

def update_appeal(case_id, key, value):
    """Обновляет одно поле в существующей апелляции в БД."""
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
    """Добавляет ответ от редактора в список ответов."""
    try:
        appeal = get_appeal(case_id)
        if appeal:
            current_answers = appeal.get('council_answers') or []
            current_answers.append(answer_data)
            update_appeal(case_id, 'council_answers', current_answers)
            print(f"Добавлен ответ от Совета по делу #{case_id}.")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось добавить ответ в дело #{case_id}: {e}")

def delete_appeal(case_id):
    """Удаляет дело из БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM appeals WHERE case_id = %s", (case_id,))
        conn.commit()
        print(f"Дело #{case_id} успешно удалено.")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось удалить дело #{case_id}: {e}")

def get_expired_appeals():
    """Возвращает все дела, у которых истек таймер."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE status = 'collecting' AND timer_expires_at IS NOT NULL AND timer_expires_at < NOW() AT TIME ZONE 'utc'")
            records = cur.fetchall()
            if not records:
                return []
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, record)) for record in records]
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить просроченные апелляции: {e}")
    return []

# --- Управление состояниями FSM ---

def get_user_state(user_id):
    """Получает состояние пользователя из БД."""
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
    """Сохраняет состояние пользователя в БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            data_json = json.dumps(data or {})
            cur.execute(
                """
                INSERT INTO user_states (user_id, state, data)
                VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                    state = EXCLUDED.state,
                                                 data = EXCLUDED.data,
                                                 updated_at = NOW();
                """,
                (user_id, state, data_json)
            )
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось установить состояние для user_id {user_id}: {e}")

def delete_user_state(user_id):
    """Удаляет состояние пользователя из БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_states WHERE user_id = %s", (user_id,))
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось удалить состояние для user_id {user_id}: {e}")


# --- Логирование ---

def log_interaction(user_id, action, case_id=None, details=""):
    """Записывает действие в лог."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interaction_logs (user_id, case_id, action, details)
                VALUES (%s, %s, %s, %s);
                """,
                (user_id, case_id, action, details)
            )
        conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось записать лог для user_id {user_id}: {e}")