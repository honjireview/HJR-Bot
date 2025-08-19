# -*- coding: utf-8 -*-
import os
import google.generativeai as genai
import appealManager
from datetime import datetime
from connectionChecker import GEMINI_MODEL_NAME

# ... (код инициализации gemini_model без изменений)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    except Exception as e:
        print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось настроить Gemini API: {e}")
else:
    print("[КРИТИЧЕСКАЯ ОШИБКА] Не найден GEMINI_API_KEY.")

def _read_file(filename: str, error_message: str) -> str:
    # ... (код без изменений)
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"[ОШИБКА] Файл {filename} не найден.")
        return error_message

def get_verdict_from_gemini(case_id, commit_hash, log_id):
    """
    Собирает все данные по делу, формирует детальный промпт и получает вердикт от Gemini.
    """
    appeal = appealManager.get_appeal(case_id)
    if not appeal:
        return "Ошибка: Не удалось найти данные по делу."

    project_rules = _read_file('rules.txt', "Устав проекта не найден.")
    instructions = _read_file('instructions.txt', "Инструкции для ИИ не найдены.")

    # ... (код формирования applicant_info, date_submitted, applicant_full_text, council_full_text без изменений)
    applicant_info = appeal.get('applicant_info', {})
    applicant_name = f"{applicant_info.get('first_name', 'Имя не указано')} (@{applicant_info.get('username', 'скрыто')})"
    created_at_dt = appeal.get('created_at')
    date_submitted = created_at_dt.strftime('%Y-%m-%d %H:%M UTC') if isinstance(created_at_dt, datetime) else "Неизвестно"
    applicant_full_text = f"""...""" # (здесь ваш длинный текст)
    council_answers_list = appeal.get('council_answers', [])
    if council_answers_list:
        council_full_text = ""
        for answer in council_answers_list:
            council_full_text += f"""...""" # (здесь ваш длинный текст)
    else:
        council_full_text = "Совет не предоставил контраргументов в установленный срок."

    # --- ИЗМЕНЕНИЕ: Подставляем новые переменные в инструкции ---
    final_instructions = instructions.format(case_id=case_id, commit_hash=commit_hash, log_id=log_id)

    prompt = f"""
{final_instructions}

**Устав проекта для анализа:**
<rules>
{project_rules}
</rules>

**ДЕТАЛИ ДЕЛА №{case_id}**
# ... (остальной код промпта без изменений)
"""

    if not gemini_model:
        return "Ошибка: Модель Gemini не инициализирована."
    try:
        print(f"--- Отправка запроса в Gemini API по делу #{case_id} (модель: {GEMINI_MODEL_NAME}) ---")
        response = gemini_model.generate_content(prompt)
        print(f"--- Ответ от Gemini API по делу #{case_id} получен ---")
        return response.text
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: {e}")
        return f"Ошибка при обращении к ИИ-арбитру. Детали: {e}"