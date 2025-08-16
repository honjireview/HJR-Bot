# -*- coding: utf-8 -*-

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

def create_appeal(case_id, initial_data):
    """Создаёт новую запись об апелляции в БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO appeals (case_id, applicant_chat_id, decision_text, status, applicant_answers, council_answers, voters_to_mention)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO NOTHING;
                """,
                (case_id, initial_data['applicant_chat_id'], initial_data['decision_text'],
                 initial_data['status'], json.dumps({}), json.dumps([]), [])
            )
        print(f"Дело #{case_id} успешно создано.")
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
                return dict(zip(columns, record))
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