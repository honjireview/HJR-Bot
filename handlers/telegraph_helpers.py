# -*- coding: utf-8 -*-
import logging
from telegraph import Telegraph
from telegraph.exceptions import TelegraphException

log = logging.getLogger("hjr-bot.telegraph")

# Создаем один экземпляр Telegraph для всего бота
telegraph = Telegraph()

# Попытка создать/получить аккаунт для бота.
try:
    access_token = telegraph.create_account(short_name='hjr-bot')
    log.info(f"Аккаунт Telegraph успешно создан/загружен. Access Token: {access_token}")
except TelegraphException as e:
    log.warning(f"Не удалось создать аккаунт Telegraph, посты будут анонимными. Ошибка: {e}")

def post_to_telegraph(title: str, content_html: str) -> str:
    """
    Публикует контент в Telegra.ph и возвращает URL страницы.
    """
    try:
        response = telegraph.create_page(
            title=title,
            html_content=content_html
        )
        url = f"https://telegra.ph/{response['path']}"
        log.info(f"Вердикт успешно опубликован в Telegraph: {url}")
        return url
    except Exception as e:
        log.error(f"Не удалось опубликовать вердикт в Telegraph: {e}")
        return None

def markdown_to_html(md_text: str) -> str:
    """
    Простой конвертер из Markdown (используемого Telegram) в HTML (для Telegraph).
    """
    text = md_text.replace('```\n', '<pre>').replace('\n```', '</pre>').replace('```', '<pre>')

    parts = text.split('**')
    for i in range(1, len(parts), 2):
        parts[i] = f"<b>{parts[i]}</b>"
    text = "".join(parts)

    parts = text.split('*')
    for i in range(1, len(parts), 2):
        parts[i] = f"<i>{parts[i]}</i>"
    text = "".join(parts)

    text = text.replace('\n', '<br>')
    return text