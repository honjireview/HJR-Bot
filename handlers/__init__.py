# -*- coding: utf-8 -*-

# Этот файл делает папку 'handlers' Python-пакетом
# и собирает все обработчики из других файлов.

from . import applicant_flow
from . import council_flow
from . import textcrafter_flow

# Словарь для отслеживания состояния пользователей.
# Он будет общим для всех модулей обработчиков.
user_states = {}

def register_all_handlers(bot):
    """
    Регистрирует все обработчики из всех модулей.
    """
    applicant_flow.register_applicant_handlers(bot, user_states)
    council_flow.register_council_handlers(bot, user_states)
    textcrafter_flow.register_textcrafter_handlers(bot, user_states)