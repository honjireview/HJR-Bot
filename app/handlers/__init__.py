# -*- coding: utf-8 -*-
from ..repositories import state_repo, appeal_repo # Относительный импорт
from . import admin, appeal, tools # Относительный импорт

def register_all_handlers(bot):
    """Регистрирует все обработчики из всех модулей."""

    @bot.message_handler(commands=['help'])
    def send_help_text(message):
        help_text = """
Здравствуйте! Я бот-ассистент проекта Honji Review.

Основные команды:
• /start - Начать подачу апелляции (для редакторов).
• /cancel - Отменить любую текущую операцию.
• `/reply [номер_дела]` - Ответить на апелляцию (для редакторов).
• /craft - Создать новый пост для канала.
"""
        bot.send_message(message.chat.id, help_text)

    @bot.message_handler(commands=['cancel'], chat_types=['private'])
    def cancel_any_process(message):
        user_id = message.from_user.id
        state = state_repo.get(user_id)
        if state:
            case_id = state.get("data", {}).get("case_id")
            # Если отменяется процесс подачи, а не ответа, удаляем дело
            if case_id and str(state.get("state")).startswith("applicant_"):
                appeal_repo.delete(case_id)
            state_repo.delete(user_id)
            bot.send_message(message.chat.id, "Текущая операция отменена.")
        else:
            bot.send_message(message.chat.id, "Нет активных операций для отмены.")

    admin.register_admin_handlers(bot)
    appeal.register_appeal_handlers(bot)
    tools.register_tools_handlers(bot)