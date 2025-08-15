# -*- coding: utf-8 -*-

import os

# --- ФАЙЛ КОНФИГУРАЦИИ ---
# Здесь хранятся все секретные данные и настройки вашего бота.

# ВАЖНО: Никогда не храните токены прямо в коде.
# Лучшая практика - использовать переменные окружения.
# os.getenv('KEY_NAME', "default_value") - пытается получить значение из переменных окружения.
# "default_value" - используется, если переменная не найдена (удобно для локальных тестов).

# Вставьте сюда токен вашего бота, полученный от @BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', "8322663955:AAEUJ-lYTIgynaJ9QEtGa0C5JQc9Q-VyiBA")

# Вставьте сюда ваш API-ключ от Google AI Studio (Gemini)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', "AIzaSyAX5f9vZ1vBLAKavihE21j2dMJ8HU6N4y4")

# ID каналов, куда будут отправляться результаты.
# Чтобы узнать ID канала, можно использовать ботов вроде @userinfobot.
# Добавьте его в канал, и он покажет ID. ID обычно начинается с -100.
APPEALS_CHANNEL_ID = os.getenv('APPEALS_CHANNEL_ID', "-1002868318167") # Канал для апелляций
EDITORS_CHANNEL_ID = os.getenv('EDITORS_CHANNEL_ID', "-1002562525160") # Редакторская группа