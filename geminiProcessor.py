# -*- coding: utf-8 -*-

import os
import google.generativeai as genai
import appealManager # Импортируем наш менеджер данных

# --- ИЗМЕНЕНИЕ: Получаем ключ напрямую из переменных окружения ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
gemini_model = None

# Настраиваем модель Gemini, если ключ найден
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
    except Exception as e:
        print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось настроить Gemini API: {e}")
else:
    print("[КРИТИЧЕСКАЯ ОШИБКА] Не найден GEMINI_API_KEY. Убедитесь, что переменная окружения установлена.")


def read_rules():
    """Читает устав из файла rules.txt."""
    try:
        with open('rules.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print("[ОШИБКА] Файл rules.txt не найден.")
        return "Устав не найден."

def get_verdict_from_gemini(case_id):
    """
    Основная функция: собирает все данные по делу, формирует промпт,
    отправляет в Gemini и возвращает вердикт.
    """
    appeal = appealManager.get_appeal(case_id)
    if not appeal:
        return "Ошибка: Не удалось найти данные по делу."

    project_rules = read_rules()

    # Формируем полные тексты позиций сторон
    applicant_full_text = f"""
Основные аргументы: {appeal.get('applicant_arguments', 'не указано')}
Ответ на вопрос о нарушении устава: {appeal['applicant_answers'].get('q1', 'не указано')}
Ответ на вопрос о справедливом решении: {appeal['applicant_answers'].get('q2', 'не указано')}
Дополнительный контекст: {appeal['applicant_answers'].get('q3', 'не указано')}
"""

    council_answers_list = appeal.get('council_answers', [])
    if council_answers_list:
        council_full_text = ""
        for answer in council_answers_list:
            council_full_text += f"""
---
{answer.get('responder_info', 'Ответ от Совета')}:
Основные контраргументы: {answer.get('main_arg', 'не указано')}
Основание (пункты устава): {answer.get('q1', 'не указано')}
Оценка аргументов заявителя: {answer.get('q2', 'не указано')}
---
"""
    else:
        council_full_text = "Совет не предоставил контраргументов в установленный срок."

    prompt = f"""
    Контекст: Ты - ИИ-арбитр проекта Honji Review. Твоя задача - вынести объективное решение, проанализировав позиции обеих сторон и устав проекта.

    Вот полный текст устава и правил проекта:
    --- УСТАВ ---
    {project_rules}
    --- КОНЕЦ УСТАВА ---

    Дело №{case_id}

    Оспариваемое решение (данные):
    ---
    {appeal.get('decision_text', 'не указано')}
    ---

    Полная позиция заявителя (аргументы и ответы на вопросы):
    ---
    {applicant_full_text}
    ---
    
    Полная позиция Совета (контраргументы и ответы на вопросы от всех ответивших редакторов):
    ---
    {council_full_text}
    ---

    Задача:
    Проанализируй позиции обеих сторон. На основе устава проекта вынеси свой вердикт. Ответ должен быть четким, структурированным и объяснять, почему ты принял такое решение. Начинай ответ со слов "Вердикт ИИ-арбитра:".
    """

    if not gemini_model:
        return "Ошибка: Модель Gemini не инициализирована."
    try:
        print(f"--- Отправка запроса в Gemini API по делу #{case_id} ---")
        response = gemini_model.generate_content(prompt)
        print(f"--- Ответ от Gemini API по делу #{case_id} получен ---")
        return response.text
    except Exception as e:
        print(f"[ОШИБКА] Gemini API: {e}")
        return f"Ошибка при обращении к ИИ-арбитру. Детали: {e}"