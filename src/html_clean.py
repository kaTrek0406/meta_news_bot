# -*- coding: utf-8 -*-
"""
Очистка HTML от «шумных» блоков и превращение в стабильный plain-текст.
- Вырезаем скрипты/стили/навигацию.
- Применяем кастомные CSS-селекторы из config.json (ignore_selectors).
- Нормализуем повторяющиеся пробелы/переводы строк.
- Убираем «штампы даты обновления», чтобы они не бомбили хэш.
"""
from __future__ import annotations

import re
from typing import Tuple, Iterable

from bs4 import BeautifulSoup, FeatureNotFound
from .config import selectors_for

_STRIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "template", "iframe"}
_WS_RE = re.compile(r"[ \t\u00a0]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")

# фразы, которые часто меняются и не влияют на суть документа
_UPDATED_PATTERNS: Iterable[re.Pattern[str]] = [
    re.compile(r"updated\s+on\s+\w+\s+\d{1,2},\s+\d{4}", re.I),
    re.compile(r"послед(нее|ний)\s+обновлен(ие|о)\s*[:\-]?\s*\d{1,2}\.\d{1,2}\.\d{2,4}", re.I),
    re.compile(r"last\s+updated\s*[:\-]?\s*\d{1,2}\s+\w+\s+\d{4}", re.I),
    re.compile(r"\bобновлено\b.*\d{4}", re.I),
]


def clean_html(html: str, url: str) -> Tuple[str, str, str]:
    """
    Возвращает (title, plain_text, cleaned_html_for_debug)
    plain_text — стабилизированный текст для хэширования/суммаризации.
    """
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except FeatureNotFound:
        # fallback
        soup = BeautifulSoup(html or "", "html.parser")

    # 1) базовые шумные теги
    for tag in list(soup.find_all(_STRIP_TAGS)):
        tag.decompose()

    # 2) кастомные селекторы по хосту
    for sel in selectors_for(url):
        try:
            for node in soup.select(sel):
                node.decompose()
        except Exception:
            # не критично, селектор мог не подойти
            continue

    # 3) заголовок
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""

    # 4) raw text
    text = soup.get_text("\n")

    # 5) убрать частые «штампы обновления»
    for pat in _UPDATED_PATTERNS:
        text = pat.sub("", text)

    # 6) нормализация пробельных символов
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    text = text.strip()

    # trimmed debug html (не обязателен, но полезно иметь)
    cleaned_html = str(soup)[:100000]  # ограничим, чтобы не раздувать память

    return title, text, cleaned_html
