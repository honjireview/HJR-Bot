# -*- coding: utf-8 -*-

# Этот модуль отвечает за хранение и управление данными апелляций в базе данных.

import psycopg
import os
import json
import threading
from connectionChecker import db_conn

def create_appeal(case_id, initial_data):
    """Создает новую запись об апелляции в БД."""
    try:
        with db_conn.cursor() as cur:
            # Преобразование списка в формат PostgreSQL и словарей в JSON
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
        db_conn.commit()
        print(f"Дело #{case_id} успешно создано/обновлено.")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось создать апелляцию #{case_id}: {e}")

def get_appeal(case_id):
    """Возвращает данные по конкретному делу из БД."""
    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals WHERE case_id = %s", (case_id,))
            record = cur.fetchone()
            if record:
                # Преобразование данных обратно в словарь
                columns = [desc[0] for desc in cur.description]
                appeal_data = dict(zip(columns, record))
                appeal_data['applicant_answers'] = json.loads(appeal_data.get('applicant_answers', '{}'))
                appeal_data['council_answers'] = json.loads(appeal_data.get('council_answers', '[]'))
                return appeal_data
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить дело #{case_id}: {e}")
    return None

def update_appeal(case_id, key, value):
    """Обновляет одно поле в существующей апелляции в БД."""
    try:
        with db_conn.cursor() as cur:
            if key == 'applicant_answers':
                value = json.dumps(value)
            elif key == 'council_answers':
                value = json.dumps(value)

            cur.execute(
                f"UPDATE appeals SET {key} = %s WHERE case_id = %s",
                (value, case_id)
            )
        db_conn.commit()
    except Exception as e:
        print(f"[ОШИБКА] Не удалось обновить дело #{case_id}: {e}")

def add_council_answer(case_id, answer_data):
    """Добавляет ответ от редактора в список ответов, используя JSONB."""
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE appeals
                SET council_answers = council_answers || %s::jsonb
                WHERE case_id = %s
                """,
                (json.dumps([answer_data]), case_id)
            )
        db_conn.commit()
        print(f"Добавлен ответ от Совета по делу #{case_id}.")
    except Exception as e:
        print(f"[ОШИБКА] Попытка добавить ответ в несуществующее дело #{case_id}: {e}")

def delete_appeal(case_id):
    """Удаляет дело из БД."""
    try:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM appeals WHERE case_id = %s", (case_id,))
        db_conn.commit()
        print(f"Дело #{case_id} успешно закрыто и удалено.")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось удалить дело #{case_id}: {e}")

def get_all_appeals():
    """Возвращает все активные апелляции."""
    try:
        with db_conn.cursor() as cur:
            cur.execute("SELECT * FROM appeals")
            records = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, record)) for record in records]
    except Exception as e:
        print(f"[ОШИБКА] Не удалось получить все апелляции: {e}")
    return []