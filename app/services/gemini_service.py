# app/services/gemini_service.py
# -*- coding: utf-8 -*-
import logging
import google.generativeai as genai
from datetime import datetime
from app.repositories import appeal_repo
from core.config import GEMINI_API_KEY
from core.precedents import PRECEDENTS

log = logging.getLogger("hjr-bot.service.gemini")

GEMINI_MODEL_NAME = "models/gemini-1.5-pro-latest"
gemini_model = None

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    except Exception as e:
        log.critical(f"Не удалось настроить Gemini API: {e}")
else:
    log.critical("Не найден GEMINI_API_KEY.")

def _read_asset(filename: str, error_message: str) -> str:
    try:
        with open(f'assets/{filename}', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        log.error(f"Файл {filename} не найден в /assets.")
        return error_message

def get_verdict(appeal: dict, commit_hash: str, bot_version: str, log_id: int):
    if not appeal:
        return "Ошибка: Не удалось найти данные по делу."

    case_id = appeal.get('case_id')
    project_rules = _read_asset('rules.txt', "Устав проекта не найден.")
    instructions = _read_asset('instructions.txt', "Инструкции для ИИ не найдены.")

    created_at_dt = appeal.get('created_at')
    date_submitted = created_at_dt.strftime('%Y-%m-%d %H:%M UTC') if isinstance(created_at_dt, datetime) else "Неизвестно"

    applicant_full_text = f"""
- Основные аргументы: {appeal.get('applicant_arguments', 'не указано')}
- Указанный на нарушение пункт устава: {appeal.get('applicant_answers', {}).get('q1', 'не указано')}
- Желаемый справедливый результат: {appeal.get('applicant_answers', {}).get('q2', 'не указано')}
- Дополнительный контекст: {appeal.get('applicant_answers', {}).get('q3', 'не указано')}
"""

    council_answers_list = appeal.get('council_answers', []) or []
    if council_answers_list:
        council_full_text = ""
        for answer in council_answers_list:
            council_full_text += f"""
---
Ответ от {answer.get('responder_info', 'Редактор Совета')}:
- Контраргументы: {answer.get('main_arg', 'не указано')}
- Обоснование по уставу: {answer.get('q1', 'не указано')}
- Оценка аргументов заявителя: {answer.get('q2', 'не указано')}
---
"""
    else:
        council_full_text = "Совет не предоставил контраргументов в установленный срок."

    precedents_text = ""
    similar_case = appeal_repo.find_similar(appeal.get('decision_text', ''), similarity_threshold=90)
    if similar_case:
        similar_case_data = appeal_repo.get_by_id(similar_case['case_id'])
        if similar_case_data:
            precedents_text = f"""
**К сведению: Прецедентное дело №{similar_case_data['case_id']}**
- **Предмет спора:** {similar_case_data.get('decision_text', 'не указано')}
- **Вердикт:** {similar_case_data.get('ai_verdict', 'не указано')}
"""
    if PRECEDENTS:
        precedents_text += "\n\n**К сведению: Архивные прецеденты**\n"
        for p in PRECEDENTS:
            precedents_text += f"- Дело №{p['case_id']}: {p['summary']} Вердикт: {p['decision_summary']}\n"


    final_instructions = instructions.format(case_id=case_id, commit_hash=commit_hash, log_id=log_id)
    final_instructions += f"\nВерсия релиза: {bot_version}"
    final_instructions += "\nОСОБОЕ ВНИМАНИЕ: При анализе строго придерживайтесь определений из раздела 'ТЕРМИНОЛОГИЯ' в уставе. **Сравни аргументы обеих сторон.**"

    prompt = f"""
{final_instructions}
{precedents_text}
**Устав проекта для анализа:**
<rules>
{project_rules}
</rules>
**ДЕТАЛИ ДЕЛА №{case_id}**
1.  **Дата подачи:** {date_submitted}
2.  **Предмет спора (оспариваемое решение):**
    ```
    {appeal.get('decision_text', 'не указано')}
    ```
3.  **АРГУМЕНТЫ ЗА отмену решения (Позиция Заявителя):**
    {applicant_full_text}
4.  **АРГУМЕНТЫ ПРОТИВ отмены решения (Позиция Совета Редакторов):**
    {council_full_text}
"""

    if not gemini_model:
        return "Ошибка: Модель Gemini не инициализирована."
    try:
        log.info(f"--- Отправка запроса в Gemini API по делу #{case_id} (модель: {GEMINI_MODEL_NAME}) ---")
        response = gemini_model.generate_content(prompt)
        log.info(f"--- Ответ от Gemini API по делу #{case_id} получен ---")
        return response.text
    except Exception as e:
        log.error(f"ОШИБКА Gemini API: {e}")
        return f"Ошибка при обращении к ИИ-арбитру. Детали: {e}"