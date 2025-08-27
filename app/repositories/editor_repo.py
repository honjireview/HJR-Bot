# app/repositories/editor_repo.py
# -*- coding: utf-8 -*-
import logging
import psycopg
from ..core.db import get_connection # <-- ИСПРАВЛЕНО

log = logging.getLogger("hjr-bot.repo.editor")

def update_list(editors_with_roles: list):
    """Полностью перезаписывает список редакторов в БД."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, is_inactive FROM editors")
            existing_statuses = {row[0]: row[1] for row in cur.fetchall()}

            cur.execute("TRUNCATE TABLE editors;")
            if not editors_with_roles:
                log.warning("Список редакторов для обновления пуст.")
                return

            editor_data = [
                (
                    info['user'].id, info['user'].username, info['user'].first_name,
                    existing_statuses.get(info['user'].id, False), info['role']
                ) for info in editors_with_roles
            ]

            with cur.copy("COPY editors (user_id, username, first_name, is_inactive, role) FROM STDIN") as copy:
                for record in editor_data:
                    copy.write_row(record)
        conn.commit()
        log.info(f"Список редакторов обновлен. Загружено {len(editors_with_roles)} пользователей.")
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось обновить список редакторов: {e}", exc_info=True)


def find_by_username(username: str):
    """Находит редактора в базе по юзернейму."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM editors WHERE username = %s", (username,))
            record = cur.fetchone()
            if record:
                columns = [desc[0] for desc in cur.description]
                return dict(zip(columns, record))
    except Exception as e:
        log.error(f"Ошибка при поиске редактора @{username}: {e}")
    return None

def update_status(user_id: int, is_inactive: bool):
    """Обновляет статус активности редактора."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("UPDATE editors SET is_inactive = %s WHERE user_id = %s", (is_inactive, user_id))
        conn.commit()
        log.info(f"Статус редактора {user_id} изменен на is_inactive={is_inactive}")
        return True
    except Exception as e:
        log.error(f"Ошибка при обновлении статуса редактора {user_id}: {e}")
    return False

def count_inactive():
    """Считает количество неактивных редакторов."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM editors WHERE is_inactive = TRUE")
            return cur.fetchone()[0]
    except Exception as e:
        log.error(f"Ошибка при подсчете неактивных редакторов: {e}")
    return 0