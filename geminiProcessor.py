# -*- coding: utf-8 -*-
import os
import google.generativeai as genai
import appealManager
from datetime import datetime
# В connectionChecker больше нет GEMINI_MODEL_NAME, так что убираем его импорт
# и определяем модель здесь, где она используется
GEMINI_MODEL_NAME = "models/gemini-1.5-flash-latest"


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

    applicant_info = appeal.get('applicant_info', {})
    applicant_name = f"{applicant_info.get('first_name', 'Имя не указано')} (@{applicant_info.get('username', 'скрыто')})"

    created_at_dt = appeal.get('created_at')
    date_submitted = created_at_dt.strftime('%Y-%m-%d %H:%M UTC') if isinstance(created_at_dt, datetime) else "Неизвестно"

    applicant_full_text = f"""
- Основные аргументы: {appeal.get('applicant_arguments', 'не указано')}
- Указанный на нарушение пункт устава: {appeal.get('applicant_answers', {}).get('q1', 'не указано')}
- Желаемый справедливый результат: {appeal.get('applicant_answers', {}).get('q2', 'не указано')}
- Дополнительный контекст: {appeal.get('applicant_answers', {}).get('q3', 'не указано')}
"""

    council_answers_list = appeal.get('council_answers', [])
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

    final_instructions = instructions.format(case_id=case_id, commit_hash=commit_hash, log_id=log_id)

    prompt = f"""
{final_instructions}

**Устав проекта для анализа:**
<rules>
{project_rules}
</rules>

**ДЕТАЛИ ДЕЛА №{case_id}**

1.  **Дата подачи:** {date_submitted}
2.  **Заявитель:** {applicant_name}
3.  **Предмет спора (оспариваемое решение):**
    ```
    {appeal.get('decision_text', 'не указано')}
    ```
4.  **Позиция Заявителя:**
    {applicant_full_text}
5.  **Позиция Совета Редакторов:**
    {council_full_text}
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

def finalize_appeal(case_id, bot, commit_hash):
    """
    Получает вердикт от ИИ, формирует ПОЛНЫЙ пост и закрывает дело.
    """
    print(f"[FINALIZE] Начинаю финальное рассмотрение дела #{case_id}")

    appeal_data = appealManager.get_appeal(case_id)
    if not appeal_data:
        print(f"[CRITICAL_ERROR] Не удалось получить данные по делу #{case_id} для финализации.")
        appealManager.log_interaction("SYSTEM", "finalize_error_no_case", case_id)
        return

    log_id = appealManager.log_interaction("SYSTEM", "finalize_start", case_id)

    # Получаем вердикт от ИИ
    ai_verdict_text = get_verdict_from_gemini(case_id, commit_hash, log_id)
    appealManager.update_appeal(case_id, "ai_verdict", ai_verdict_text)

    # --- ИСПРАВЛЕНО: Формирование полного и структурированного поста ---

    # Собираем данные по делу для поста
    created_at_dt = appeal_data.get('created_at')
    date_submitted = created_at_dt.strftime('%Y-%m-%d %H:%M UTC') if isinstance(created_at_dt, datetime) else "Неизвестно"

    applicant_answers = appeal_data.get('applicant_answers', {}) or {}
    applicant_position = (
        f"*Аргументы:* {appeal_data.get('applicant_arguments', 'не указано')}\n"
        f"*Нарушенный пункт устава:* {applicant_answers.get('q1', 'не указано')}\n"
        f"*Справедливый результат:* {applicant_answers.get('q2', 'не указано')}\n"
        f"*Доп. контекст:* {applicant_answers.get('q3', 'не указано')}"
    )

    council_answers_list = appeal_data.get('council_answers', []) or []
    if council_answers_list:
        council_position = ""
        for answer in council_answers_list:
            council_position += (
                f"\n\n\n*Ответ от {answer.get('responder_info', 'Редактор Совета')}:*\n"
                f"*Контраргументы:* {answer.get('main_arg', 'не указано')}\n"
                f"*Обоснование по уставу:* {answer.get('q1', 'не указано')}\n"
                f"*Оценка аргументов заявителя:* {answer.get('q2', 'не указано')}"
            )
    else:
        council_position = "_Совет не предоставил контраргументов._"

    # Собираем финальное сообщение
    final_message = (
        f"⚖️ *Итоги рассмотрения апелляции №{case_id}*\n\n"
        f"**Дата подачи:** {date_submitted}\n"
        f"**Версия бота (коммит):** `{commit_hash}`\n"
        f"**ID Вердикта:** `{log_id}`\n\n"
        f"--- \n\n"
        f"📄 **Позиция Заявителя:**\n"
        f"{applicant_position}\n\n"
        f"--- \n\n"
        f"👥 **Позиция Совета Редакторов:**\n"
        f"{council_position}\n\n"
        f"--- \n\n"
        f"🤖 **{ai_verdict_text}**" # Вердикт ИИ теперь является заключительной частью
    )

    # Отправляем сообщение
    applicant_chat_id = appeal_data.get('applicant_chat_id')
    appeals_channel_id = os.getenv('APPEALS_CHANNEL_ID')

    try:
        if applicant_chat_id:
            bot.send_message(applicant_chat_id, final_message, parse_mode="Markdown")
        if appeals_channel_id:
            bot.send_message(appeals_channel_id, final_message, parse_mode="Markdown")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось отправить вердикт по делу #{case_id}: {e}")
        appealManager.log_interaction("SYSTEM", "send_verdict_error", case_id, str(e))

    appealManager.update_appeal(case_id, "status", "closed")
    appealManager.log_interaction("SYSTEM", "appeal_closed", case_id)
    print(f"[FINALIZE] Дело #{case_id} успешно закрыто.")