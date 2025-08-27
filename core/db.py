# core/db.py
# -*- coding: utf-8 -*-
import os
import psycopg
import logging
import google.generativeai as genai
from .config import DATABASE_URL, GEMINI_API_KEY

log = logging.getLogger("hjr-bot.core.db")
db_conn = None

def _normalize_dsn(dsn: str) -> str:
    if not dsn: return dsn
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql://", 1)
    return dsn

def _create_and_migrate_tables(conn: psycopg.Connection):
    """
    Создаёт и/или обновляет таблицы в базе данных до актуальной схемы.
    """
    with conn.cursor() as cur:
        # Основная таблица апелляций
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS appeals (
                                                           case_id INTEGER PRIMARY KEY,
                                                           applicant_chat_id BIGINT,
                                                           decision_text TEXT,
                                                           applicant_arguments TEXT,
                                                           applicant_answers JSONB,
                                                           council_answers JSONB,
                                                           total_voters INTEGER,
                                                           status TEXT,
                                                           expected_responses INTEGER,
                                                           timer_expires_at TIMESTAMPTZ,
                                                           ai_verdict TEXT,
                                                           message_thread_id INTEGER,
                                                           is_reviewed BOOLEAN DEFAULT FALSE,
                                                           review_data JSONB,
                                                           commit_hash VARCHAR(40),
                        verdict_log_id INTEGER
                        );
                    """)

        # Таблица состояний (FSM)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_states (
                                                               user_id TEXT PRIMARY KEY,
                                                               state TEXT,
                                                               data JSONB,
                                                               updated_at TIMESTAMPTZ DEFAULT NOW()
                        );
                    """)

        # Таблица редакторов
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS editors (
                                                           user_id BIGINT PRIMARY KEY,
                                                           username TEXT,
                                                           first_name TEXT,
                                                           is_inactive BOOLEAN DEFAULT FALSE,
                                                           role TEXT DEFAULT 'editor'
                    );
                    """)
    conn.commit()
    log.info("Проверка и миграция таблиц завершена.")

def get_connection():
    """Возвращает активное соединение с БД, переподключаясь при необходимости."""
    global db_conn
    if db_conn is None or db_conn.closed:
        if not connect_to_db():
            raise RuntimeError("Не удалось установить/восстановить соединение с БД.")
    return db_conn

def connect_to_db() -> bool:
    """Устанавливает соединение с PostgreSQL и проверяет структуру таблицы."""
    global db_conn
    dsn = _normalize_dsn(DATABASE_URL)
    if not dsn:
        log.critical("PostgreSQL: Не найдена переменная окружения DATABASE_URL.")
        return False
    try:
        db_conn = psycopg.connect(dsn, autocommit=False)
        _create_and_migrate_tables(db_conn)
        db_conn.autocommit = True
        log.info("PostgreSQL: Соединение установлено и таблицы проверены.")
        return True
    except Exception as e:
        log.critical(f"PostgreSQL: Не удалось подключиться или настроить таблицу. {e}")
        return False

def check_all_connections(bot) -> bool:
    """
    Проверяет доступность всех API: Telegram, Gemini и PostgreSQL.
    """
    log.info("--- Начало проверки API ---")

    try:
        bot_info = bot.get_me()
        log.info(f"[OK] Telegram API: Успешно подключен как @{bot_info.username}")
    except Exception as e:
        log.critical(f"[ОШИБКА] Telegram API: {e}")
        return False

    if not GEMINI_API_KEY:
        log.critical("[ОШИБКА] Gemini API: Не найден GEMINI_API_KEY.")
        return False
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        genai.get_model("models/gemini-1.5-pro-latest")
        log.info("[OK] Gemini API: Ключ успешно прошел аутентификацию.")
    except Exception as e:
        log.critical(f"[ОШИБКА] Gemini API: {e}")
        return False

    if not connect_to_db():
        return False

    log.info("--- Все проверки API пройдены успешно! ---")
    return True