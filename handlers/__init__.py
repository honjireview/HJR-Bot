# -*- coding: utf-8 -*-

# Этот файл делает папку 'handlers' Python-пакетом
# и собирает все обработчики из других файлов.

from . import applicant_flow
from . import council_flow
from . import textcrafter_flow

"""
Handlers package — экспорт регистрации обработчиков.
"""
from .applicant_flow import register_applicant_handlers

__all__ = ["register_applicant_handlers"]

# Словарь для отслеживания состояния пользователей.
# Он будет общим для всех модулей обработчиков.
user_states = {}

def register_all_handlers(bot):
    """
    Регистрирует все обработчики из всех модулей.
    """

    # --- НОВЫЙ ОБРАБОТЧИК ДЛЯ КОМАНДЫ /help ---
    @bot.message_handler(commands=['help'])
    def send_help_text(message):
        help_text = """
Здравствуйте! Я бот-ассистент проекта Honji Review. Моя задача — помогать с рутинными процессами и обеспечивать справедливость при помощи ИИ.

Вот мои основные функции и команды:

---

*Система Апелляций*

Этот модуль позволяет подать апелляцию на решение Совета Редакторов. Процесс полностью автоматизирован и проходит в несколько этапов для обеспечения объективности.

*Основные команды:*
• `/start` - Начать новую процедуру подачи апелляции.
• `/cancel` - Полностью отменить текущий процесс подачи апелляции на любом этапе.
• `/reply [номер_дела]` - (Только для редакторов) Подать контраргументы по конкретному делу.

---

*TextCrafter (Создание постов)*

Этот модуль помогает создавать форматированные посты для отправки в каналы.

*Основные команды:*
• `/craft` - Начать создание нового поста.
• `/tsettings` - Настроить канал по умолчанию для отправки постов.
• `/tpreview` - Посмотреть, как будет выглядеть пост перед отправкой.
• `/tcancel` - Отменить процесс создания поста.

---

*Открытый исходный код*

Весь мой код полностью открыт. Вы можете посмотреть, как я устроен, предложить улучшения или использовать его для своих проектов.

Ссылка на репозиторий:
https://github.com/honjireview/HJR-Bot
"""
        bot.send_message(message.chat.id, help_text, disable_web_page_preview=True)

    # Регистрация остальных обработчиков
    applicant_flow.register_applicant_handlers(bot, user_states)
    council_flow.register_council_handlers(bot, user_states)
    textcrafter_flow.register_textcrafter_handlers(bot, user_states)