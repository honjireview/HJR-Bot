# -*- coding: utf-8 -*-

import os
import google.generativeai as genai
import telebot
from telebot import apihelper
import psycopg_binary as psycopg

# Глобальная переменная для хранения соединения с БД
db_conn = None

def check_db_connection():
    """
    Проверяет соединение с базой данных PostgreSQL.
    Возвращает True при успехе, False при ошибке.
    """
    global db_conn
    try:
        db_conn = psycopg.connect(
            dbname=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT', 5432)
        )
        with db_conn.cursor() as cur:
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
                                                               status TEXT
                        );
                        """)
            db_conn.commit()
        print("[OK] PostgreSQL: Соединение с базой данных успешно. Таблица 'appeals' проверена.")
        return True
    except Exception as e:
        print(f"[ОШИБКА] PostgreSQL: Не удалось подключиться к базе данных. Ошибка: {e}")
        return False

def check_all_apis(bot):
    """
    Проверяет доступность всех API: Telegram, Gemini и PostgreSQL.
    """
    print("--- Начало проверки API ---")

    # 1. Проверка Telegram API
    try:
        bot_info = bot.get_me()
        print(f"[OK] Telegram API: Успешно подключен как @{bot_info.username}")
    except apihelper.ApiTelegramException as e:
        if e.error_code == 401:
            print("[ОШИБКА] Telegram API: Неверный токен бота.")
        else:
            print(f"[ОШИБКА] Telegram API: Не удалось подключиться. Код: {e.error_code}, Описание: {e.description}")
        return False
    except Exception as e:
        print(f"[ОШИБКА] Telegram API: Неизвестная ошибка: {e}")
        return False

    # 2. Проверка Gemini API
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    if not GEMINI_API_KEY:
        print("[ОШИБКА] Gemini API: Не найден GEMINI_API_KEY.")
        return False

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        genai.get_model('models/gemini-1.5-flash-latest')
        print("[OK] Gemini API: Ключ успешно прошел аутентификацию.")
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: Не удалось подключиться. Проверьте GEMINI_API_KEY. Детали: {e}")
        return False

    # 3. Проверка PostgreSQL
    if not check_db_connection():
        return False

    print("--- Все проверки API пройдены успешно! ---")
    return True