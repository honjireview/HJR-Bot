# -*- coding: utf-8 -*-
import os
import logging
import re
import google.generativeai as genai
import appealManager
from datetime import datetime
from precedents import PRECEDENTS
from handlers.telegraph_helpers import post_to_telegraph, markdown_to_html

log = logging.getLogger("hjr-bot.gemini")

GEMINI_MODEL_NAME = "models/gemini-1.5-pro-latest"

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

def get_verdict_from_gemini(appeal: dict, commit_hash: str, bot_version: str, log_id: int):
    if not appeal:
        return "Ошибка: Не удалось найти данные по делу."

    case_id = appeal.get('case_id')
    project_rules = _read_file('rules.txt', "Устав проекта не найден.")
    instructions = _read_file('instructions.txt', "Инструкции для ИИ не найдены.")

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
    similar_case = appealManager.find_similar_appeal(appeal.get('decision_text', ''), similarity_threshold=90)
    if similar_case:
        similar_case_data = appealManager.get_appeal(similar_case['case_id'])
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

def finalize_appeal(appeal_data: dict, bot, commit_hash: str, bot_version: str):
    if not isinstance(appeal_data, dict) or 'case_id' not in appeal_data:
        print(f"[CRITICAL_ERROR] В finalize_appeal переданы некорректные данные.")
        return

    case_id = appeal_data['case_id']
    log.info(f"[FINALIZE] Начинаю финальное рассмотрение дела #{case_id}")

    if not appealManager.are_arguments_meaningful(appeal_data.get('applicant_arguments', '')):
        log.warning(f"[FINALIZE_SKIP] Дело #{case_id} пропущено из-за отсутствия осмысленных аргументов.")
        appealManager.update_appeal(case_id, "status", "closed_invalid")
        appealManager.log_interaction("SYSTEM", "appeal_closed_invalid", case_id, "No valid arguments provided.")
        return

    log_id = appealManager.log_interaction("SYSTEM", "finalize_start", case_id)

    ai_verdict_text = get_verdict_from_gemini(appeal_data, commit_hash, bot_version, log_id)
    appealManager.update_appeal(case_id, "ai_verdict", ai_verdict_text)

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

    final_message_markdown = (
        f"⚖️ *Итоги рассмотрения апелляции №{case_id}*\n\n"
        f"**Дата подачи:** {date_submitted}\n"
        f"**Версия релиза:** `{bot_version}`\n"
        f"**Версия коммита:** `{commit_hash}`\n"
        f"**ID Вердикта:** `{log_id}`\n\n"
        f"--- \n\n"
        f"📌 **Предмет спора:**\n"
        f"```\n{appeal_data.get('decision_text', 'не указано')}\n```\n\n"
        f"--- \n\n"
        f"📄 **Позиция Заявителя (анонимно):**\n"
        f"{applicant_position}\n\n"
        f"--- \n\n"
        f"👥 **Позиция Совета Редакторов:**\n"
        f"{council_position}\n\n"
        f"--- \n\n"
        f"🤖 **{ai_verdict_text}**"
    )

    applicant_chat_id = appeal_data.get('applicant_chat_id')
    appeals_channel_id = os.getenv('APPEALS_CHANNEL_ID')

    clean_verdict_markdown = re.sub(r'</?rules>', '', final_message_markdown)

    log.info(f"Публикую вердикт по делу #{case_id} в Telegraph...")
    final_message_html = markdown_to_html(clean_verdict_markdown)
    page_url = post_to_telegraph(f"Вердикт по апелляции №{case_id}", final_message_html)

    if page_url:
        message_to_send = (
            f"⚖️ *Вердикт по апелляции №{case_id} готов.*\n\n"
            f"Ознакомиться с полным решением можно по ссылке:\n{page_url}"
        )
    else:
        message_to_send = clean_verdict_markdown[:4000] + "\n\n_[Сообщение было урезано из-за ошибки публикации]_"

    try:
        if applicant_chat_id:
            bot.send_message(applicant_chat_id, message_to_send, parse_mode="Markdown")
        if appeals_channel_id:
            bot.send_message(appeals_channel_id, message_to_send, parse_mode="Markdown")
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось отправить вердикт по делу #{case_id}: {e}")
        appealManager.log_interaction("SYSTEM", "send_verdict_error", case_id, str(e))

    appealManager.update_appeal(case_id, "status", "closed")
    appealManager.log_interaction("SYSTEM", "appeal_closed", case_id)
    log.info(f"[FINALIZE] Дело #{case_id} успешно закрыто.")

# ИСПРАВЛЕНО: Добавлена полная реализация функции пересмотра
def get_review_from_gemini(appeal: dict, commit_hash: str, bot_version: str, log_id: int):
    """
    Формирует усложненный промпт для ПЕРЕСМОТРА дела и получает финальный вердикт.
    """
    case_id = appeal.get('case_id')
    project_rules = _read_file('rules.txt', "Устав проекта не найден.")

    # Формируем текст новых аргументов
    review_data = appeal.get('review_data', {})
    new_arguments_list = review_data.get('new_arguments', [])
    new_arguments_text = ""
    if new_arguments_list:
        for arg in new_arguments_list:
            new_arguments_text += f"- Аргумент от {arg['author']}: {arg['argument']}\n"
    else:
        new_arguments_text = "Новых аргументов для пересмотра предоставлено не было."

    # Формируем информацию о голосовании за пересмотр
    poll_data = review_data.get("poll", {})
    poll_text = f"Вопрос: '{poll_data.get('question', '')}', Результаты: "
    poll_text += ", ".join([f"'{opt.get('text')}': {opt.get('voter_count')} гол." for opt in poll_data.get('options', [])])

    # Новый, усложненный промпт
    prompt = f"""
Ты — ИИ-арбитр высшей инстанции. Перед тобой дело №{case_id}, по которому уже был вынесен вердикт.
Совет Редакторов провел голосование ({poll_text}) и решил пересмотреть это дело.
Внимательно изучи **первоначальное решение** и **новые аргументы** от Совета.
Твоя задача — **переоценить** свой прошлый анализ. Если ты считаешь, что новые аргументы являются весомыми и меняют суть дела, измени свой вердикт. Если нет — оставь его в силе, но **обязательно объясни, почему** новые аргументы не повлияли на твое решение.
Это решение будет **окончательным и не подлежит дальнейшему обжалованию** (согласно пункту 8.6 Устава).

**Устав проекта для анализа:**
<rules>
{project_rules}
</rules>

**ДЕТАЛИ ПЕРВОНАЧАЛЬНОГО ДЕЛА №{case_id}**
{appeal.get('decision_text', '')}
- Аргументы заявителя: {appeal.get('applicant_arguments', '')}
- Ответы Совета: {appeal.get('council_answers', [])}

**ПРЕДЫДУЩИЙ ВЕРДИКТ:**
    {appeal.get('ai_verdict', 'Предыдущий вердикт не найден.')}
    
**НОВЫЕ АРГУМЕНТЫ ДЛЯ ПЕРЕСМОТРА:**
{new_arguments_text}
"""

    if not gemini_model:
        return "Ошибка: Модель Gemini не инициализирована."
    try:
        log.info(f"--- Отправка запроса на ПЕРЕСМОТР в Gemini API по делу #{case_id} ---")
        response = gemini_model.generate_content(prompt)
        log.info(f"--- Ответ на ПЕРЕСМОТР от Gemini API по делу #{case_id} получен ---")
        return response.text
    except Exception as e:
        log.error(f"ОШИБКА Gemini API при пересмотре: {e}")
        return f"Ошибка при обращении к ИИ-арбитру. Детали: {e}"

def finalize_review(appeal_data: dict, bot, commit_hash: str, bot_version: str):
    case_id = appeal_data['case_id']
    log.info(f"[FINALIZE_REVIEW] Начинаю ПЕРЕСМОТР дела #{case_id}")

    log_id = appealManager.log_interaction("SYSTEM", "review_finalize_start", case_id)

    # Получаем финальный вердикт
    ai_review_verdict = get_review_from_gemini(appeal_data, commit_hash, bot_version, log_id)

    # Сохраняем финальный вердикт в review_data, чтобы не затереть старый
    review_data = appeal_data.get('review_data', {})
    review_data['final_verdict'] = ai_review_verdict
    appealManager.update_appeal(case_id, "review_data", review_data)

    # Формируем и отправляем сообщение
    final_verdict_text = (
        f"⚖️ *Финальные итоги рассмотрения апелляции №{case_id} (ПОСЛЕ ПЕРЕСМОТРА)*\n\n"
        f"**ID Финального Вердикта:** `{log_id}`\n"
        f"**Версия релиза:** `{bot_version}`\n"
        f"**Версия коммита:** `{commit_hash}`\n\n"
        f"--- \n\n"
        f"🤖 **{ai_review_verdict}**"
    )

    applicant_chat_id = appeal_data.get('applicant_chat_id')
    appeals_channel_id = os.getenv('APPEALS_CHANNEL_ID')

    try:
        # Логика отправки через Telegraph
        log.info(f"Публикую вердикт по ПЕРЕСМОТРУ дела #{case_id} в Telegraph...")
        final_message_html = markdown_to_html(final_verdict_text)
        page_url = post_to_telegraph(f"Финальный вердикт по апелляции №{case_id} (Пересмотр)", final_message_html)

        if page_url:
            message_to_send = (
                f"⚖️ *Финальный вердикт по апелляции №{case_id} (после пересмотра) готов.*\n\n"
                f"Ознакомиться с окончательным решением можно по ссылке:\n{page_url}"
            )
        else:
            message_to_send = final_verdict_text[:4000] + "\n\n_[Сообщение было урезано из-за ошибки публикации]_"

        if applicant_chat_id:
            bot.send_message(applicant_chat_id, message_to_send, parse_mode="Markdown")
        if appeals_channel_id:
            bot.send_message(appeals_channel_id, message_to_send, parse_mode="Markdown")
    except Exception as e:
        log.error(f"[ОШИБКА] Не удалось отправить вердикт по пересмотру дела #{case_id}: {e}")

    appealManager.update_appeal(case_id, "status", "closed_after_review")
    appealManager.log_interaction("SYSTEM", "appeal_closed_after_review", case_id)
    log.info(f"[FINALIZE_REVIEW] Дело #{case_id} успешно закрыто после пересмотра.")