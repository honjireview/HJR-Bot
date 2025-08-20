# -*- coding: utf-8 -*-

import os
import psycopg
import google.generativeai as genai
from telebot import apihelper

db_conn = None

def _normalize_dsn(dsn: str) -> str:
    # ... (код без изменений) ...
    if not dsn: return dsn
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql://", 1)
    return dsn

def _create_and_migrate_tables(conn: psycopg.Connection):
    """
    Создаёт и/или обновляет таблицы в базе данных до актуальной схемы.
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
                                                           ai_verdict TEXT
                    );
                    """)

        cur.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS message_thread_id INTEGER;")

        # ИСПРАВЛЕНО: Убрана колонка, которую мы не можем получить
        # cur.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS discussion_context TEXT;")

        # ИСПРАВЛЕНО: Новые колонки для системы пересмотра
        cur.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS is_reviewed BOOLEAN DEFAULT FALSE;")
        cur.execute("ALTER TABLE appeals ADD COLUMN IF NOT EXISTS review_data JSONB;")

    conn.commit()
    print("Проверка и миграция таблицы 'appeals' завершена.")

def check_db_connection() -> bool:
    # ... (остальной код без изменений) ...
    """
    Устанавливает соединение с PostgreSQL и проверяет структуру таблицы.
    """
    global db_conn
    dsn = _normalize_dsn(os.getenv("DATABASE_URL"))
    if not dsn:
        print("[ОШИБКА] PostgreSQL: Не найдена переменная окружения DATABASE_URL.")
        return False
    try:
        # Устанавливаем соединение с автокоммитом false для миграций
        db_conn = psycopg.connect(dsn, autocommit=False)
        _create_and_migrate_tables(db_conn)
        db_conn.autocommit = True # Возвращаем автокоммит для обычной работы
        print("[OK] PostgreSQL: Соединение установлено и таблица проверена.")
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
        genai.get_model("models/gemini-1.5-pro-latest")
        print("[OK] Gemini API: Ключ успешно прошел аутентификацию.")
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: {e}")
        return False

    if not check_db_connection():
        return False

    print("--- Все проверки API пройдены успешно! ---")
    return True