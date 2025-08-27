# -*- coding: utf-8 -*-
"""
Парсер ссылок t.me — возвращает (from_chat_id, message_id) или None.
from_chat_id: int для приватных чатов/каналов (включая -100...),
              или строка вида '@username' для публичных каналов/профилей.
"""
import re
from typing import Optional, Tuple, Union

def parse_message_link(text: str) -> Optional[Tuple[Union[int, str], int]]:
    s = (text or "").strip()
    if not s:
        return None

    # Уберём протокол и параметры
    s_clean = re.sub(r'^\s*https?://', '', s, flags=re.IGNORECASE).split('?', 1)[0].split('#', 1)[0].strip()

    # Приватные чаты/каналы: t.me/c/<internal_id>/.../<message_id>
    # internal_id в ссылке — без префикса -100; фактический chat_id = -100<internal_id>
    if '/c/' in s_clean:
        nums = re.findall(r'/([0-9]+)', s_clean)
        # Ожидаем как минимум internal id и message id
        if len(nums) >= 2:
            try:
                internal = nums[0]
                msg_id = nums[-1]
                return int(f"-100{internal}"), int(msg_id)
            except Exception:
                return None

    # Публичные каналы/профили: t.me/<username>/<message_id>
    m = re.search(r'^(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})(?:/|$)', s_clean, flags=re.IGNORECASE)
    if m:
        username = m.group(1)
        nums = re.findall(r'/([0-9]+)', s_clean)
        if nums:
            try:
                return f"@{username}", int(nums[-1])
            except Exception:
                return None
        return None

    # Варианты без протокола: "@chan 1234", "chan/1234", "channel 1234"
    m2 = re.search(r'@([A-Za-z0-9_]{3,})', s_clean)
    nums2 = re.findall(r'([0-9]{3,})', s_clean)
    if m2 and nums2:
        try:
            return f"@{m2.group(1)}", int(nums2[-1])
        except Exception:
            return None

    return None