# app/repositories/state_repo.py
# -*- coding: utf-8 -*-
import json
import logging
from ..core.db import get_connection # <-- ИСПРАВЛЕНО

log = logging.getLogger("hjr-bot.repo.state")

def get(user_id: str):
    """Получает состояние пользователя по ID."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT state, data FROM user_states WHERE user_id = %s", (str(user_id),))
            record = cur.fetchone()
            if record:
                return {"state": record[0], "data": record[1] or {}}
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось получить состояние для user_id {user_id}: {e}")
    return None

def set(user_id: str, state: str, data: dict = None):
    """Устанавливает состояние для пользователя по ID."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            data_json = json.dumps(data or {})
            cur.execute(
                """
                INSERT INTO user_states (user_id, state, data)
                VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                    state = EXCLUDED.state, data = EXCLUDED.data, updated_at = NOW();
                """,
                (str(user_id), state, data_json)
            )
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось установить состояние для user_id {user_id}: {e}")

def delete(user_id: str):
    """Удаляет состояние пользователя по ID."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_states WHERE user_id = %s", (str(user_id),))
        conn.commit()
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось удалить состояние для user_id {user_id}: {e}")