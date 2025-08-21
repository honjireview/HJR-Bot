# -*- coding: utf-8 -*-
import appealManager

def register_all_handlers(bot):
    """
    Регистрирует все обработчики из всех модулей.
    """
    from . import applicant_flow
    from . import council_flow
    from . import textcrafter_flow
    from . import admin_flow
    from . import review_flow

    user_states = {}

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

    @bot.message_handler(commands=['cancel'], chat_types=['private'])
    def cancel_any_process(message):
        user_id = message.from_user.id
        state = appealManager.get_user_state(user_id)
        if state:
            if state.get("data", {}).get("case_id"):
                case_id = state["data"]["case_id"]
                if not str(state.get("state")).startswith("council_"):
                    appealManager.delete_appeal(case_id)
            appealManager.delete_user_state(user_id)
            bot.send_message(message.chat.id, "Текущая операция отменена.")
        else:
            bot.send_message(message.chat.id, "У вас нет активных операций, которые можно было бы отменить.")

    # --- Регистрация всех потоков ---
    applicant_flow.register_applicant_handlers(bot)
    council_flow.register_council_handlers(bot)
    review_flow.register_review_handlers(bot)
    textcrafter_flow.register_textcrafter_handlers(bot, user_states)
    admin_flow.register_admin_handlers(bot)