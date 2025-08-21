# -*- coding: utf-8 -*-
import logging
from telegraph import Telegraph
from telegraph.exceptions import TelegraphException
# ИСПРАВЛЕНО: Импортируем стандартную и надежную библиотеку для конвертации
import markdown

log = logging.getLogger("hjr-bot.telegraph")

telegraph = Telegraph()

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

# ИСПРАВЛЕНО: Старая самописная функция полностью заменена
def markdown_to_html(md_text: str) -> str:
    """
    Конвертирует Markdown в HTML с помощью стандартной библиотеки,
    поддерживая все вложенные стили.
    """
    # Включаем расширения для поддержки блоков кода ``` и переносов строк
    html = markdown.markdown(md_text, extensions=['fenced_code', 'nl2br'])
    return html