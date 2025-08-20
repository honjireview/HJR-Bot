# -*- coding: utf-8 -*-

def register_all_handlers(bot):
    """
    Регистрирует все обработчики из всех модулей.
    Импорты модулей происходят внутри, чтобы избежать циклических зависимостей.
    """
    from . import applicant_flow
    from . import council_flow
    from . import textcrafter_flow
    from . import admin_flow # <-- ДОБАВЛЕНО

    @bot.message_handler(commands=['help'])
    def send_help_text(message):
        help_text = """
Здравствуйте! Я бот-ассистент проекта Honji Review. Моя задача — помогать с рутинными процессами и обеспечивать справедливость при помощи ИИ.

Вот мои основные функции и команды:

---

Система Апелляций

Этот модуль позволяет подать апелляцию на решение Совета Редакторов. Процесс полностью автоматизирован и проходит в несколько этапов для обеспечения объективности.

Основные команды:
• /start - Начать новую процедуру подачи апелляции (только для редакторов).
• /cancel - Полностью отменить текущий процесс подачи апелляции на любом этапе.
• `/reply [номер_дела]` - Подать контраргументы по конкретному делу (только для редакторов).

---

TextCrafter (Создание постов)

Этот модуль помогает создавать форматированные посты для отправки в каналы.

Основные команды:
• /craft - Начать создание нового поста.
• /tsettings - Настроить канал по умолчанию для отправки постов.
• /tpreview - Посмотреть, как будет выглядеть пост перед отправкой.
• /tcancel - Отменить процесс создания поста.

Мой сайт - https://hjrbotreview.up.railway.app/bot.html
"""
        bot.send_message(message.chat.id, help_text, disable_web_page_preview=True)

    @bot.message_handler(commands=['getid'])
    def send_chat_id(message):
        chat_id = message.chat.id
        bot.reply_to(message, f"ID этого чата: `{chat_id}`")


    # --- Регистрация всех потоков ---
    applicant_flow.register_applicant_handlers(bot)
    council_flow.register_applicant_handlers(bot)
    textcrafter_flow.register_textcrafter_handlers(bot)
    admin_flow.register_admin_handlers(bot) # <-- ДОБАВЛЕНО