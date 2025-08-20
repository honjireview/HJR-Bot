# -*- coding: utf-8 -*-
import logging
from telegraph import Telegraph
from telegraph.exceptions import TelegraphException

log = logging.getLogger("hjr-bot.telegraph")

# Создаем один экземпляр Telegraph для всего бота
telegraph = Telegraph()

# Попытка создать/получить аккаунт для бота.
# Это нужно, чтобы в будущем можно было редактировать посты.
try:
    telegraph.create_account(short_name='hjr-bot')
    log.info("Аккаунт Telegraph успешно создан/загружен.")
except TelegraphException as e:
    log.warning(f"Не удалось создать аккаунт Telegraph, посты будут анонимными. Ошибка: {e}")

def post_to_telegraph(title: str, content_html: str) -> str:
    """
    Публикует контент в Telegra.ph и возвращает URL страницы.

    Args:
        title (str): Заголовок страницы.
        content_html (str): Содержимое страницы в формате HTML.

    Returns:
        str: URL созданной страницы или None в случае ошибки.
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
    Поддерживает **жирный**, *курсив*, ```код```.
    """
    text = md_text.replace('**', '<b>').replace('**', '</b>') # Для жирного
    text = text.replace('*', '<i>').replace('*', '</i>')     # Для курсива
    text = text.replace('```\n', '<pre>').replace('\n```', '</pre>') # Для блоков кода
    text = text.replace('\n', '<br>') # Переносы строк
    return text