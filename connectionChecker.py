# -*- coding: utf-8 -*-

import os
import google.generativeai as genai
from telebot import apihelper

def check_all_apis(bot):
    """
    Проверяет доступность API Telegram и Gemini.
    """
    print("--- Начало проверки API ---")

    # 1. Проверка Telegram API
    try:
        bot_info = bot.get_me()
        print(f"[OK] Telegram API: Успешно подключен как @{bot_info.username}")
    except apihelper.ApiTelegramException as e:
        if e.error_code == 401:
            print("[ОШИБКА] Telegram API: Неверный токен бота. Проверьте переменную окружения BOT_TOKEN.")
        else:
            print(f"[ОШИБКА] Telegram API: Не удалось подключиться. Код: {e.error_code}, Описание: {e.description}")
        return False
    except Exception as e:
        print(f"[ОШИБКА] Telegram API: Произошла неизвестная ошибка: {e}")
        return False

    # 2. Проверка Gemini API
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    if not GEMINI_API_KEY:
        print("[ОШИБКА] Gemini API: Не найден GEMINI_API_KEY. Убедитесь, что переменная окружения установлена.")
        return False

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        genai.get_model('models/gemini-1.5-flash-latest')
        print("[OK] Gemini API: Ключ API успешно прошел аутентификацию.")
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: Не удалось подключиться. Проверьте GEMINI_API_KEY. Детали: {e}")
        return False

    print("--- Все проверки API пройдены успешно! ---")
    return True