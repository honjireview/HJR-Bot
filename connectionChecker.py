# -*- coding: utf-8 -*-

import os
import psycopg
import google.generativeai as genai
from telebot import apihelper

db_conn = None

def _normalize_dsn(dsn: str) -> str:
    """
    Приводит префикс 'postgres://' к 'postgresql://' — иногда нужно для psycopg.
    Возвращает неизменённый DSN, если изменений не требуется.
    """
    if not dsn:
        return dsn
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql://", 1)
    return dsn

def _print_conn_debug_from_dsn(dsn: str):
    # Показываем только непарольную диагностическую информацию (host/port/db/user), защищая секреты.
    try:
        info = {}
        # Попытка получить поля через psycopg (если доступно)
        try:
            # psycopg.conninfo.parse_dsn не всегда доступен в старых версиях
            # поэтому используем urllib.parse
            from urllib.parse import urlparse
            p = urlparse(dsn)
            info = {
                "host": p.hostname,
                "port": p.port,
                "user": p.username,
                "dbname": p.path[1:] if p.path else None
            }
        except Exception:
            pass # fallback: простая разборка URL
        host = info.get("host") or "socket"
        port = info.get("port") or "5432"
        user = info.get("user") or ""
        dbname = info.get("dbname") or ""
        print(f"[DEBUG] Попытка подключения к БД: host={host} port={port} db={dbname} user={user}")
    except Exception:
        print("[DEBUG] Попытка подключения к БД: не удалось разобрать DSN (скрываю детали)")

def _create_table_if_needed(conn: psycopg.Connection):
    # Создаёт таблицу appeals, если её нет
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
                                                           timer_expires_at TIMESTAMP
                    );
                    """)
    try:
        conn.commit()
    except Exception:
        pass

def check_db_connection() -> bool:
    """
    Пытается установить соединение с PostgreSQL.
    Возвращает True при успешном подключении и создании таблицы, иначе False.
    """
    global db_conn

    raw_dsn = os.getenv("DATABASE_URL")
    if raw_dsn:
        dsn = _normalize_dsn(raw_dsn)
        _print_conn_debug_from_dsn(dsn)
        try:
            db_conn = psycopg.connect(dsn)
            try:
                db_conn.autocommit = True
            except Exception:
                pass
            _create_table_if_needed(db_conn)
            print("[OK] PostgreSQL: Соединение установлено через DATABASE_URL.")
            return True
        except Exception as e:
            print(f"[ОШИБКА] PostgreSQL (DATABASE_URL): {e}")

    host = os.getenv("PGHOST")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    dbname = os.getenv("PGDATABASE")
    port = os.getenv("PGPORT", "5432")

    if not (host and user and password and dbname):
        print("[ОШИБКА] PostgreSQL: Нет необходимых PG-переменных окружения.")
        return False

    print(f"[DEBUG] Попытка подключения по переменным: host={host} port={port} db={dbname} user={user}")
    try:
        db_conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            sslmode="require"
        )
        try:
            db_conn.autocommit = True
        except Exception:
            pass
        _create_table_if_needed(db_conn)
        print("[OK] PostgreSQL: Соединение установлено по PGHOST/PGUSER/PGDATABASE.")
        return True
    except Exception as e:
        print(f"[ОШИБКА] PostgreSQL (PGHOST/...): {e}")
        return False

def check_all_apis(bot) -> bool:
    """
    Проверяет доступность Telegram API, Gemini API и PostgreSQL.
    Возвращает True если всё в порядке.
    """
    print("--- Начало проверки API ---")

    try:
        bot_info = bot.get_me()
        print(f"[OK] Telegram API: Успешно подключен как @{bot_info.username}")
    except apihelper.ApiTelegramException as e:
        if getattr(e, "error_code", None) == 401:
            print("[ОШИБКА] Telegram API: Неверный токен бота.")
        else:
            code = getattr(e, "error_code", "unknown")
            desc = getattr(e, "description", str(e))
            print(f"[ОШИБКА] Telegram API: Не удалось подключиться. Код: {code}, Описание: {desc}")
        return False
    except Exception as e:
        print(f"[ОШИБКА] Telegram API: Неизвестная ошибка: {e}")
        return False

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        print("[ОШИБКА] Gemini API: Не найден GEMINI_API_KEY.")
        return False
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        genai.get_model("models/gemini-1.5-flash-latest")
        print("[OK] Gemini API: Ключ успешно прошел аутентификацию.")
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: Не удалось подключиться. Детали: {e}")
        return False

    if not check_db_connection():
        return False

    print("--- Все проверки API пройдены успешно! ---")
    return True