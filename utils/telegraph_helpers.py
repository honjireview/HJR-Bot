# utils/telegraph_helpers.py
# -*- coding: utf-8 -*-
import logging
from telegraph import Telegraph
from telegraph.exceptions import TelegraphException
import markdown

log = logging.getLogger("hjr-bot.utils.telegraph")

telegraph = Telegraph()
try:
    telegraph.create_account(short_name='hjr-bot')
    log.info("Аккаунт Telegraph успешно создан/загружен.")
except TelegraphException as e:
    log.warning(f"Не удалось создать аккаунт Telegraph, посты будут анонимными. Ошибка: {e}")

def post_to_telegraph(title: str, content_html: str) -> str:
    try:
        response = telegraph.create_page(title=title, html_content=content_html)
        url = f"https://telegra.ph/{response['path']}"
        log.info(f"Контент успешно опубликован в Telegraph: {url}")
        return url
    except Exception as e:
        log.error(f"Не удалось опубликовать в Telegraph: {e}")
        return None

def markdown_to_html(md_text: str) -> str:
    return markdown.markdown(md_text, extensions=['fenced_code', 'nl2br'])