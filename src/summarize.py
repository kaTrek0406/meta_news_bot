# -*- coding: utf-8 -*-
"""
Подготовка HTML и компактное русское резюме под карточки + утилиты нормализации/секций:
- normalize_plain(): чистим шум (даты, служебные хвосты), схлопываем пробелы.
- extract_sections(): разбор на секции (h2/h3 + прилегающие p/li), считаем сигнатуры.
- summarize_rules(): сжатие в RU-формат для карточек: лид ≤150 + до 3 буллетов ≤120.
Если ИИ недоступен — аккуратный фолбэк.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Tuple, List, Dict

from bs4 import BeautifulSoup
from .llm_client import chat, LLMError  # используем общий клиент

DEFAULT_LANG = os.getenv("LLM_OUTPUT_LANG", "ru")
_WHITESPACE_RE = re.compile(r"[ \t\x0a]+")

STRIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "template", "iframe"}

# шумовые конструкции (даты/обновления/служебные хвосты)
_NOISE_RE = re.compile(
    r"(?im)"
    r"(Last\s+updated|Updated\s+on|Updated:|Опубликовано|Обновлено|Дата обновления)[^\n]*$|"
    r"\b\d{4}-\d{2}-\d{2}\b|"
    r"\b\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}\b"
)

_TAIL_RE = re.compile(r"(?im)^(Назад к .*?|Back to .*?|Help Center|Справочный центр).*$")


def compute_sig(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def normalize_plain(plain: str) -> str:
    """Стабилизируем текст для подсчёта хэша/сигнатур (минус шум и даты)."""
    s = (plain or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = _NOISE_RE.sub("", s)
    s = _TAIL_RE.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def text_from_html(html: str) -> Tuple[str, str]:
    """Вернуть (title, text) без мусора."""
    soup = BeautifulSoup(html or "", "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""

    for tag in list(soup.find_all(STRIP_TAGS)):
        tag.decompose()

    text = soup.get_text("\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return title, text


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\- ]+", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "section"


def extract_sections(html: str) -> List[Dict[str, str]]:
    """
    Разбор на секции: каждая начинается с h2/h3, затем все p/li до следующего заголовка.
    Возвращает список dict: {id, title, text, sig}
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in list(soup.find_all(STRIP_TAGS)):
        tag.decompose()

    sections: List[Dict[str, str]] = []
    current_title = None
    current_buf: List[str] = []

    def _flush():
        nonlocal current_title, current_buf
        if not current_title:
            return
        body = " ".join(current_buf).strip()
        norm = normalize_plain((current_title or "") + "\n" + body)
        sections.append(
            {
                "id": _slug(current_title),
                "title": current_title.strip(),
                "text": body,
                "sig": compute_sig(norm),
            }
        )
        current_title, current_buf = None, []

    for node in soup.find_all(["h2", "h3", "p", "li"]):
        name = node.name.lower()
        if name in ("h2", "h3"):
            # новая секция
            if current_title:
                _flush()
            ttl = node.get_text(" ").strip()
            if ttl:
                current_title = ttl
                current_buf = []
        else:
            if current_title:
                txt = node.get_text(" ").strip()
                if len(txt) >= 2:
                    current_buf.append(txt)

    _flush()
    return sections


# ======================== суммаризация ========================

def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)].rstrip() + "…"


def _fallback_summarize(plain: str) -> str:
    """Если ИИ недоступен: берём первое информативное предложение + ещё 2 коротких строки."""
    if not plain:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", plain)
    parts = [p.strip() for p in parts if p and len(p.strip()) >= 15]
    lead = _clip(parts[0] if parts else plain, 150)
    bullets: List[str] = []
    for p in parts[1:]:
        bullets.append(_clip(p, 120))
        if len(bullets) >= 3:
            break
    out = [lead]
    for b in bullets:
        out.append(f"- {b}")
    return "\n".join(out)


def _build_prompt_ru(plain: str) -> str:
    return (
        "Ты — редактор. Сожми следующий текст до формата карточки для Telegram:\n"
        "— Первая строка: краткий лид (≤150 символов).\n"
        "— Далее до 3 буллетов (каждый ≤120 символов), по одному на строке, начинай каждый с «- ».\n"
        "— Никаких заголовков, эмодзи, маркированных списков кроме «- », без лишней разметки.\n"
        "— Пиши по-русски, просто и по делу.\n\n"
        "Текст для сжатия:\n"
        f"{plain}"
    )


def summarize_rules(html_or_text: str) -> str:
    """
    Суммирование изменений/правил:
    Вход — сырой HTML/текст; выходим на компактный RU-формат:
        <лид ≤150>\n
        - <буллет ≤120>\n
        - <буллет ≤120>\n
        - <буллет ≤120>
    """
    # Если пришёл HTML — вычистим до plain
    title, plain = text_from_html(html_or_text)
    source = plain or html_or_text or ""
    if not source.strip():
        return ""

    prompt = _build_prompt_ru(source)
    try:
        resp = chat(prompt=prompt, system="Редактируй и сжимай по правилам. Язык: русский.")
        lines = [ln.rstrip() for ln in (resp or "").splitlines() if ln.strip()]
        if not lines:
            return _fallback_summarize(source)

        lead = _clip(lines[0], 150)
        bullets_raw = [ln for ln in lines[1:] if ln.startswith("-")]
        if not bullets_raw:
            body = "\n".join(lines[1:]).strip()
            parts = re.split(r"(?<=[.!?])\s+", body)
            bullets_raw = [f"- {p.strip()}" for p in parts if p and len(p.strip()) >= 10]

        bullets = []
        for b in bullets_raw:
            b = b.lstrip("-").strip()
            if not b:
                continue
            bullets.append(f"- {_clip(b, 120)}")
            if len(bullets) >= 3:
                break

        out = [lead]
        out.extend(bullets)
        return "\n".join(out).strip()

    except LLMError:
        return _fallback_summarize(source)
