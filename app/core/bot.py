# core/bot.py
# -*- coding: utf-8 -*-
import telebot
from .config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN)