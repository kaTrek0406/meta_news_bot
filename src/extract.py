# -*- coding: utf-8 -*-
import re
from bs4 import BeautifulSoup

def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s or " ").strip()
    return s

def extract_text(html: str) -> str:
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # удаляем шумные блоки
    for sel in ["script", "style", "noscript", "header", "footer", "nav", "aside"]:
        for t in soup.select(sel):
            t.decompose()

    # title как заголовок
    title = (soup.title.string if soup.title and soup.title.string else "").strip()

    texts = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        txt = _clean(tag.get_text(" "))
        if len(txt) >= 5:
            texts.append(txt)

    parts = []
    if title:
        parts.append(title)
    parts.extend(texts)
    return "\n".join(parts)[:15000]
