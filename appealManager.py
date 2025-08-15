# -*- coding: utf-8 -*-

import os
import json
import random
import threading

# используем модуль как namespace, чтобы брать connection динамично
import connectionChecker
import pandas as pd
import io

def _get_conn():
    """
    Возвращает текущее соединение из connectionChecker.
    Бросает RuntimeError, если соединение не установлено.
    """
    conn = connectionChecker.db_conn
    if conn is None:
        raise RuntimeError("DB connection not initialized (connectionChecker.db_conn is None)")
    return conn

def create_appeal(case_id, initial_data):
    """Создаёт новую запись об апелляции в БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            voters = initial_data.get('voters_to_mention', [])
            answers = json.dumps(initial_data.get('applicant_answers', {}))
            council_answers = json.dumps(initial_data.get('council_answers', []))

            cur.execute(
                """
                INSERT INTO appeals (case_id, applicant_chat_id, decision_text, applicant_arguments,
                                     applicant_answers, council_answers, voters_to_mention, total_voters, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO UPDATE SET
                    applicant_chat_id = EXCLUDED.applicant_chat_id,
                                                 decision_text = EXCLUDED.decision_text,
                                                 applicant_answers = EXCLUDED.applicant_answers,
                                                 council_answers = EXCLUDED.council_answers,
                                                 voters_to_mention = EXCLUDED.voters_to_mention,
                                                 total_voters = EXCLUDED.total_voters,
                                                 status = EXCLUDED.status;
                """,
                (case_id, initial_data['applicant_chat_id'], initial_data['decision_text'],
                 initial_data.get('applicant_arguments'), answers, council_answers,
                 voters, initial_data.get('total_voters'), initial_data['status'])
            )
        try:
            conn.commit()
        except Exception:
            # Некоторые managed-conn могут быть в autocommit — игнорируем
            pass
        print(f"Дело #{case_id} успешно создано/обновлено.")
    except RuntimeError as re:
        print(f"[ОШИБКА] Создание апелляции #{case_id} прервано: {re}")
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
                appeal_data['applicant_answers'] = json.loads(appeal_data.get('applicant_answers', '{}') or '{}')
                appeal_data['council_answers'] = json.loads(appeal_data.get('council_answers', '[]') or '[]')
                return appeal_data
    except RuntimeError as re:
        print(f"[ОШИБКА] Получение дела #{case_id} прервано: {re}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить дело #{case_id}: {e}")
    return None

def update_appeal(case_id, key, value):
    """Обновляет одно поле в существующей апелляции в БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if key == 'applicant_answers' or key == 'council_answers':
                value = json.dumps(value)
            cur.execute(
                f"UPDATE appeals SET {key} = %s WHERE case_id = %s",
                (value, case_id)
            )
        try:
            conn.commit()
        except Exception:
            pass
    except RuntimeError as re:
        print(f"[ОШИБКА] Обновление дела #{case_id} прервано: {re}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось обновить дело #{case_id}: {e}")

def add_council_answer(case_id, answer_data):
    """Добавляет ответ от редактора в список ответов, используя JSONB."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE appeals
                SET council_answers = COALESCE(council_answers, '[]'::jsonb) || %s::jsonb
                WHERE case_id = %s
                """,
                (json.dumps([answer_data]), case_id)
            )
        try:
            conn.commit()
        except Exception:
            pass
        print(f"Добавлен ответ от Совета по делу #{case_id}.")
    except RuntimeError as re:
        print(f"[ОШИБКА] Добавление ответа в дело #{case_id} прервано: {re}")
    except Exception as e:
        print(f"[ОШИБКА] Попытка добавить ответ в несуществующее дело #{case_id}: {e}")

def delete_appeal(case_id):
    """Удаляет дело из БД."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM appeals WHERE case_id = %s", (case_id,))
        try:
            conn.commit()
        except Exception:
            pass
        print(f"Дело #{case_id} успешно закрыто и удалено.")
    except RuntimeError as re:
        print(f"[ОШИБКА] Удаление дела #{case_id} прервано: {re}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось удалить дело #{case_id}: {e}")

def get_all_appeals():
    """Возвращает все активные апелляции."""
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals")
            records = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, record)) for record in records]
    except RuntimeError as re:
        print(f"[ОШИБКА] Получение всех дел прервано: {re}")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить все апелляции: {e}")
    return []