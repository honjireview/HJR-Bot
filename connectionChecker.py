# -*- coding: utf-8 -*-

import config  # Импортируем наш файл с токеном
import google.generativeai as genai # Импортируем библиотеку Gemini
from telebot import apihelper # Импортируем для отлова ошибок API

def check_all_apis(bot):
    """
    Проверяет доступность API Telegram и Gemini.
    Принимает экземпляр бота в качестве аргумента.
    Возвращает True, если все проверки пройдены, иначе False.
    """
    print("--- Начало проверки API ---")

    # 1. Проверка Telegram API
    try:
        bot_info = bot.get_me()
        print(f"[OK] Telegram API: Успешно подключен как @{bot_info.username}")
    except apihelper.ApiTelegramException as e:
        if e.error_code == 401:
            print("[ОШИБКА] Telegram API: Неверный токен бота. Проверьте BOT_TOKEN в файле config.py.")
        else:
            print(f"[ОШИБКА] Telegram API: Не удалось подключиться. Код: {e.error_code}, Описание: {e.description}")
        return False
    except Exception as e:
        print(f"[ОШИБКА] Telegram API: Произошла неизвестная ошибка: {e}")
        return False

    # 2. Проверка Gemini API
    try:
        # Настраиваем Gemini API с ключом из конфига
        genai.configure(api_key=config.GEMINI_API_KEY)
        # Делаем простой и бесплатный запрос с самым актуальным названием модели
        genai.get_model('models/gemini-1.5-flash-latest') # <-- ИЗМЕНЕНИЕ ЗДЕСЬ
        print("[OK] Gemini API: Ключ API успешно прошел аутентификацию.")
    except Exception as e:
        # Отлавливаем общую ошибку, так как библиотека может выдавать разные типы исключений
        print(f"[ОШИБКА] Gemini API: Не удалось подключиться. Проверьте GEMINI_API_KEY. Детали: {e}")
        return False

    print("--- Все проверки API пройдены успешно! ---")
    return True