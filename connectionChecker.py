# -*- coding: utf-8 -*-

import os
import psycopg
import google.generativeai as genai
from telebot import apihelper

db_conn = None

def _normalize_dsn(dsn: str) -> str:
    if not dsn: return dsn
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql://", 1)
    return dsn

def _create_and_migrate_tables(conn: psycopg.Connection):
    """
    Создаёт или обновляет все необходимые таблицы.
    """
    with conn.cursor() as cur:
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS appeals (
                                                           case_id INTEGER PRIMARY KEY,
                                                           applicant_chat_id BIGINT,
                                                           decision_text TEXT,
                                                           applicant_arguments TEXT,
                                                           applicant_answers JSONB,
                                                           council_answers JSONB,
                                                           voters_to_mention TEXT[],
                                                           total_voters INTEGER,
                                                           status TEXT,
                                                           expected_responses INTEGER,
                                                           timer_expires_at TIMESTAMPTZ,
                                                           ai_verdict TEXT,
                                                           created_at TIMESTAMPTZ,
                                                           applicant_info JSONB
                    );
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_states (
                                                               user_id BIGINT PRIMARY KEY,
                                                               state VARCHAR(255),
                        data JSONB,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                        );
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS interaction_logs (
                                                                    log_id SERIAL PRIMARY KEY,
                                                                    user_id BIGINT,
                                                                    case_id INTEGER,
                                                                    action VARCHAR(255),
                        details TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                        );
                    """)
    conn.commit()
    print("Проверка и миграция таблиц 'appeals', 'user_states', 'interaction_logs' завершена.")

def check_db_connection() -> bool:
    """
    Устанавливает соединение с PostgreSQL и проверяет структуру таблицы.
    """
    global db_conn
    dsn = _normalize_dsn(os.getenv("DATABASE_URL"))
    if not dsn:
        print("[ОШИБКА] PostgreSQL: Не найдена переменная окружения DATABASE_URL.")
        return False
    try:
        db_conn = psycopg.connect(dsn, autocommit=True)
        _create_and_migrate_tables(db_conn)
        print("[OK] PostgreSQL: Соединение установлено и таблицы проверены.")
        return True
    except Exception as e:
        print(f"[ОШИБКА] PostgreSQL: Не удалось подключиться или настроить таблицу. {e}")
        return False

def check_all_apis(bot) -> bool:
    """
    Проверяет доступность всех API: Telegram, Gemini и PostgreSQL.
    """
    print("--- Начало проверки API ---")

    try:
        bot_info = bot.get_me()
        print(f"[OK] Telegram API: Успешно подключен как @{bot_info.username}")
    except Exception as e:
        print(f"[ОШИБКА] Telegram API: {e}")
        return False

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        print("[ОШИБКА] Gemini API: Не найден GEMINI_API_KEY.")
        return False
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # --- ИЗМЕНЕНИЕ: Проверяем доступность Pro-модели ---
        genai.get_model("models/gemini-1.5-pro-latest")
        print("[OK] Gemini API: Ключ успешно прошел аутентификацию для модели Pro.")
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: {e}")
        return False

    if not check_db_connection():
        return False

    print("--- Все проверки API пройдены успешно! ---")
    return True