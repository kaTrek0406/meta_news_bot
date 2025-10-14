# -*- coding: utf-8 -*-
import logging
import os
import asyncio
from html import escape
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
)

from ..storage import load_cache
from ..pipeline import run_update, get_stats
from ..llm_client import translate_compact_html  # автоперевод/сжатие
from ..smart_formatter import format_change_smart  # умное форматирование

log = logging.getLogger(__name__)

# Функция для очистки HTML от неподдерживаемых Telegram тегов
def _sanitize_telegram_html(html: str) -> str:
    """Удаляет или заменяет HTML теги, не поддерживаемые Telegram.
    Telegram поддерживает только: <b>, <i>, <u>, <s>, <a>, <code>, <pre>
    """
    # Заменяем h1-h6 на bold
    html = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'<b>\1</b>', html, flags=re.IGNORECASE | re.DOTALL)
    # Убираем неподдерживаемые теги (НЕ трогаем b, i, u, s, a, code, pre)
    html = re.sub(r'</?(?:div|span|p|br|hr|ul|ol|li|table|tr|td|th|thead|tbody|h[1-6]|img|form|input|button|script|style)[^>]*>', '', html, flags=re.IGNORECASE)
    return html

CATS = {
    "news_policy": ("⚖", "Политика"),
    "news_product": ("🛠", "Продукты"),
    "news_status":  ("📈", "Статусы"),
    "news_dev":     ("💻", "Разработчикам"),
    "news_regulation": ("📜", "Регулирование"),
    "news_media":   ("📰", "Прочее"),
}
ALL_TAG = "all"

_last_pages: Dict[int, List[int]] = defaultdict(list)
_last_menu: Dict[int, int] = {}
_tips: Dict[int, int] = {}

AUTO_TRANSLATE = os.getenv("AUTO_TRANSLATE_DIFFS", "1") == "1"
MAX_NOTIFY_CHARS = int(os.getenv("MAX_NOTIFY_CHARS", "1400"))
DEV_ID = int(os.getenv("TELEGRAM_DEV_CHAT_ID", "527824690") or "0")

def _items() -> List[dict]:
    data = load_cache() or {}
    items = data.get("items", [])
    return [x for x in items if isinstance(x, dict) and x.get("tag") and x.get("url")]

def _count_by_tag(items: List[dict]) -> Dict[str, int]:
    d: Dict[str, int] = defaultdict(int)
    for it in items:
        d[it.get("tag", "")] += 1
    d[ALL_TAG] = len(items)
    return d

def _build_menu(counts: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    rows.append([InlineKeyboardButton(f"✅ Все ({counts.get(ALL_TAG, 0)})", callback_data=f"cat:{ALL_TAG}")])
    for tag, (emoji, title) in CATS.items():
        n = counts.get(tag, 0)
        rows.append([InlineKeyboardButton(f"{emoji} {title} ({n})", callback_data=f"cat:{tag}")])
    rows.append([InlineKeyboardButton("🔄 Обновить источники", callback_data="refresh")])
    rows.append([InlineKeyboardButton("ℹ️ Статус", callback_data="status")])
    return InlineKeyboardMarkup(rows)

def _paginate(items: List[dict], page_size: int) -> List[List[dict]]:
    out, cur = [], []
    for it in items:
        cur.append(it)
        if len(cur) >= page_size:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out

_MAX_TITLE = 40
_MAX_MAIN = 150
_MAX_BULLETS = 3
_MAX_BULLET_LEN = 120
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)].rstrip() + "…"

def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    parts = _SENT_SPLIT.split(text)
    for p in parts:
        p = p.strip("–—-:;•· ").strip()
        if len(p) >= 15:
            return p
    return text

def _extract_bullets(summary: str) -> list[str]:
    lines = [ln.strip() for ln in (summary or "").splitlines()]
    bulletish = [ln for ln in lines if ln.startswith(("-", "•", "—", "*"))]
    cleaned = [ln.lstrip("-•—* ").strip() for ln in bulletish if ln]
    if not cleaned:
        parts = _SENT_SPLIT.split(summary or "")
        parts = [p.strip() for p in parts if 10 <= len(p.strip()) <= _MAX_BULLET_LEN + 20]
        cleaned = parts
    out = []
    for ln in cleaned:
        if not ln:
            continue
        out.append(_clip(ln, _MAX_BULLET_LEN))
        if len(out) >= _MAX_BULLETS:
            break
    return out

def _pretty_item(it: dict) -> str:
    tag = it.get("tag", "")
    emo = CATS.get(tag, ("•", ""))[0]
    raw_title = (it.get("title") or it.get("url") or "").strip()
    title = escape(_clip(raw_title, _MAX_TITLE))

    summary = (it.get("summary") or "").strip()
    main = escape(_clip(_first_sentence(summary), _MAX_MAIN)) if summary else "—"
    bullets = [f"• {escape(b)}" for b in _extract_bullets(summary)[:_MAX_BULLETS]]
    url = escape((it.get("url") or "").strip())

    lines = [f"{emo} <b>{title}</b>", main]
    if bullets:
        lines.extend(bullets)
    lines.append(f"🔗 <a href=\"{url}\">Подробнее</a>")
    return "\n".join(lines)

def _safe_join(blocks: List[str], hard_limit: int = 3500) -> Tuple[str, int]:
    out, used, total = [], 0, 0
    for b in blocks:
        need = len(b) + (2 if out else 0)
        if total + need > hard_limit:
            break
        out.append(b); total += need; used += 1
    return ("\n\n".join(out) if out else "⚠️ В этой категории пока нет данных."), used

async def _delete_msgs(chat_id: int, context: ContextTypes.DEFAULT_TYPE, ids: List[int]):
    while ids:
        mid = ids.pop()
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass

async def _delete_old_pages(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await _delete_msgs(chat_id, context, _last_pages.get(chat_id, []))

async def _delete_old_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    mid = _last_menu.pop(chat_id, None)
    if mid:
        await _delete_msgs(chat_id, context, [mid])

async def _send_tip(update: Update) -> None:
    q = update.callback_query
    if not q:
        return
    m = await q.message.reply_text("⏳ Формирую страницу…")
    _tips[q.message.chat_id] = m.message_id

async def _clear_tip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    mid = _tips.pop(q.message.chat_id, None)
    if not mid:
        return
    try:
        await context.bot.delete_message(chat_id=q.message.chat_id, message_id=mid)
    except Exception:
        pass

async def _send_page(update: Update, context: ContextTypes.DEFAULT_TYPE, tag: str, page_idx: int = 0):
    q = update.callback_query
    chat_id = q.message.chat_id

    items = _items()
    if tag != ALL_TAG:
        items = [it for it in items if it.get("tag") == tag]

    if not items:
        await q.message.reply_text("⚠️ В этой категории пока нет данных.")
        return

    page_size = int(get_stats().get("page_size", 4))
    pages = _paginate(items, page_size)
    page_idx %= max(1, len(pages))
    page = pages[page_idx]

    blocks = [_pretty_item(it) for it in page]
    text, _ = _safe_join(blocks, hard_limit=3500)

    rows = []
    if len(pages) > 1:
        rows.append([
            InlineKeyboardButton("⬅️", callback_data=f"page:{tag}:{(page_idx-1) % len(pages)}"),
            InlineKeyboardButton(f"{page_idx+1}/{len(pages)}", callback_data="noop"),
            InlineKeyboardButton("➡️", callback_data=f"page:{tag}:{(page_idx+1) % len(pages)}"),
        ])
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data="menu")])
    kb = InlineKeyboardMarkup(rows)

    await _delete_old_pages(chat_id, context)

    m: Message = await q.message.reply_html(
        text,
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    _last_pages[chat_id].append(m.message_id)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    items = _items()
    counts = _count_by_tag(items)
    kb = _build_menu(counts)
    await _delete_old_menu(chat_id, context)
    m = await update.message.reply_text("Выберите категорию:", reply_markup=kb)
    _last_menu[chat_id] = m.message_id

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "ℹ️ <b>Справка</b>\n\n"
        "Команды:\n"
        "/start — показать категории\n"
        "/refresh — обновить источники\n"
        "/status — статистика\n"
        "/help — помощь\n"
        "/testdispatch — тест ежедневной рассылки (только разработчик)\n\n"
        "Навигация кнопками ⬅️➡️. Старые страницы и меню удаляются автоматически.\n"
    )
    await update.message.reply_html(txt, disable_web_page_preview=True)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_stats()
    await update.message.reply_html(
        "<b>📊 Статистика</b>\n\n"
        f"Источников: {s['sources_configured']}\n"
        f"Кэшировано записей: {s['items_cached']}\n"
        f"Последняя проверка (UTC): {s['latest_utc']}\n"
        f"Размер страницы: {s['page_size']}\n"
    )

def _format_detailed_diff(detail: dict) -> List[str]:
    H_LIMIT = 3500
    title = escape(detail.get("title", "") or detail.get("url", ""))
    url = escape(detail.get("url", ""))
    blocks: List[str] = []

    header = f"• <b>{title}</b>"
    cur = header

    def _flush():
        nonlocal cur
        if cur.strip():
            blocks.append(cur)
        cur = ""

    def _append(line: str):
        nonlocal cur
        add = ("\n" if cur else "") + line
        if len(cur) + len(add) > H_LIMIT:
            _flush()
            cur = line
        else:
            cur += add

    def _norm(s: str) -> str:
        s = (s or "").strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def _is_space_equal(a: str, b: str) -> bool:
        return (a or "").replace(" ", "") == (b or "").replace(" ", "")

    def _pair_contains(p_big: Tuple[str, str], p_small: Tuple[str, str]) -> bool:
        aw, an = p_big
        bw, bn = p_small
        return (bw in aw and bn in an) or (aw in bw and an in bn)

    section_pairs = []
    for s in (detail.get("section_diffs") or []):
        if s.get("type") == "changed":
            for pair in s.get("changed", []):
                was = _norm(pair.get("was", ""))
                now = _norm(pair.get("now", ""))
                if was or now:
                    section_pairs.append((was, now))

    gd = detail.get("global_diff") or {}
    changed = gd.get("changed") or []
    removed = gd.get("removed") or []
    added   = gd.get("added") or []

    filtered_changed: List[Tuple[str, str]] = []
    for pair in changed:
        was = _norm(pair.get("was", ""))
        now = _norm(pair.get("now", ""))
        if not (was or now):
            continue
        if _is_space_equal(was, now):
            continue
        dup = False
        for sp in section_pairs:
            if _pair_contains((was, now), sp):
                dup = True
                break
        if not dup:
            filtered_changed.append((was, now))

    if filtered_changed or added or removed:
        _append("")
        _append("✏️ <b>Изменения на странице</b>")
        for was, now in filtered_changed:
            _append(f"— Было: “{escape(was)}”")
            _append(f"— Стало: “{escape(now)}”")
        if added:
            _append("➕ <b>Добавлено:</b>")
            for ln in added:
                _append(f"— {escape(_norm(ln))}")
        if removed:
            _append("➖ <b>Удалено:</b>")
            for ln in removed:
                _append(f"— {escape(_norm(ln))}")

    for s in (detail.get("section_diffs") or []):
        typ = s.get("type")
        ttl = escape(s.get("title", ""))
        if typ == "added":
            _append("➕ <b>Добавлено:</b>")
            for ln in s.get("added", []):
                _append(f"— {escape(_norm(ln))}")
        elif typ == "removed":
            _append("➖ <b>Удалено:</b>")
            for ln in s.get("removed", []):
                _append(f"— {escape(_norm(ln))}")
        elif typ == "changed":
            _append(f"✏️ <b>Изменено:</b> ({ttl})")
            for pair in s.get("changed", []):
                was = _norm(pair.get("was", ""))
                now = _norm(pair.get("now", ""))
                if _is_space_equal(was, now):
                    continue
                _append(f"— Было: “{escape(was)}”")
                _append(f"— Стало: “{escape(now)}”")
            for ln in s.get("removed_inline", []):
                _append(f"— Было (доп.): “{escape(_norm(ln))}”")
            for ln in s.get("added_inline", []):
                _append(f"— Стало (доп.): “{escape(_norm(ln))}”")

    tail = f"\n🔗 {url}" if url else ""
    if len(cur) + len(tail) > H_LIMIT:
        _flush()
        if tail.strip():
            blocks.append(tail.strip())
    else:
        cur += tail
        _flush()

    return blocks

def _needs_translation(s: str) -> bool:
    if not AUTO_TRANSLATE:
        return False
    en = len(re.findall(r"[A-Za-z]", s))
    total = max(1, len(s))
    return en / total > 0.15 or len(s) > MAX_NOTIFY_CHARS

def _is_meaningful_change(detail: dict) -> bool:
    """
    Определяет, является ли изменение значимым для таргетолога.
    Игнорирует: изменения только дат, версий, незначительные правки текста.
    """
    gd = detail.get("global_diff") or {}
    changed = gd.get("changed") or []
    added = gd.get("added") or []
    removed = gd.get("removed") or []
    
    # Если есть добавления или удаления - это всегда значимо
    if added or removed:
        return True
    
    # Анализируем изменения
    for pair in changed:
        was = (pair.get("was", "") or "").lower()
        now = (pair.get("now", "") or "").lower()
        
        # Убираем даты из сравнения
        was_no_dates = re.sub(r'\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[a-zа-я]*\s+\d{4}\b', '', was)
        now_no_dates = re.sub(r'\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)[a-zа-я]*\s+\d{4}\b', '', now)
        
        # Убираем версии (v1.0, version 2, etc)
        was_no_ver = re.sub(r'\bv?\d+\.\d+(?:\.\d+)?\b', '', was_no_dates)
        now_no_ver = re.sub(r'\bv?\d+\.\d+(?:\.\d+)?\b', '', now_no_dates)
        
        # Убираем лишние пробелы
        was_clean = re.sub(r'\s+', ' ', was_no_ver).strip()
        now_clean = re.sub(r'\s+', ' ', now_no_ver).strip()
        
        # Если после очистки тексты разные - изменение значимое
        if was_clean != now_clean and len(now_clean) > 10:
            return True
    
    return False

async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tip = await update.message.reply_text("⏳ Обновляю источники…")
    res = await run_update()
    try:
        await context.bot.delete_message(update.effective_chat.id, tip.message_id)
    except Exception:
        pass

    details = res.get("details") or []
    # Фильтруем только значимые изменения
    meaningful_details = [d for d in details if _is_meaningful_change(d)]
    
    msg = f"✅ Обновление завершено.\nВсего изменений: {len(details)}\nЗначимых для таргетинга: {len(meaningful_details)}"
    await update.message.reply_text(msg)

    if not meaningful_details:
        await update.message.reply_text("🟢 Все изменения незначительные (обновление дат, версий, и т.д.)")
        return

    for d in meaningful_details:
        # Используем умное форматирование
        parts = format_change_smart(d)
        for p in parts:
            out = p
            if _needs_translation(out):
                try:
                    out = translate_compact_html(out, target_lang="ru", max_len=MAX_NOTIFY_CHARS)
                except Exception:
                    out = p
            out = _sanitize_telegram_html(out)
            await update.message.reply_html(out, disable_web_page_preview=True)
            # Задержка для избежания flood control
            await asyncio.sleep(0.05)

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    try:
        if data == "menu":
            chat_id = q.message.chat_id
            items = _items()
            counts = _count_by_tag(items)
            kb = _build_menu(counts)
            await _delete_old_menu(chat_id, context)
            await _delete_old_pages(chat_id, context)
            m = await q.message.reply_text("Выберите категорию:", reply_markup=kb)
            _last_menu[chat_id] = m.message_id

        elif data.startswith("cat:"):
            tag = data.split(":", 1)[1]
            await _send_tip(update)
            await _send_page(update, context, tag, page_idx=0)
            await _clear_tip(update, context)

        elif data.startswith("page:"):
            _, tag, sidx = data.split(":")
            await _send_tip(update)
            await _send_page(update, context, tag, page_idx=int(sidx))
            await _clear_tip(update, context)

        elif data == "refresh":
            await q.answer("⏳ Обновляю…", show_alert=False)
            res = await run_update()
            
            details = res.get("details") or []
            # Фильтруем только значимые изменения
            meaningful_details = [d for d in details if _is_meaningful_change(d)]
            
            msg = f"✅ Обновление завершено.\nВсего изменений: {len(details)}\nЗначимых для таргетинга: {len(meaningful_details)}"
            await q.message.reply_text(msg)

            if not meaningful_details:
                await q.message.reply_text("🟢 Все изменения незначительные (обновление дат, версий, и т.д.)")
            else:
                for d in meaningful_details:
                    # Используем умное форматирование
                    parts = format_change_smart(d)
                    for p in parts:
                        out = p
                        if _needs_translation(out):
                            try:
                                out = translate_compact_html(out, target_lang="ru", max_len=MAX_NOTIFY_CHARS)
                            except Exception:
                                out = p
                        out = _sanitize_telegram_html(out)
                        await q.message.reply_html(out, disable_web_page_preview=True)
                        # Задержка для избежания flood control
                        await asyncio.sleep(0.05)

        elif data == "status":
            s = get_stats()
            await q.message.reply_html(
                "<b>📊 Статистика</b>\n\n"
                f"Источников: {s['sources_configured']}\n"
                f"Кэшировано записей: {s['items_cached']}\n"
                f"Последняя проверка (UTC): {s['latest_utc']}\n"
                f"Размер страницы: {s['page_size']}\n"
            )

        else:
            await q.answer()
    except Exception as e:
        log.error("on_button error: %s", e, exc_info=True)
        await q.message.reply_text("⚠️ Произошла ошибка при обработке запроса. Попробуй ещё раз.")

# dev-команда: прогон ежедневной рассылки только в ЛС разработчику
async def cmd_testdispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if DEV_ID and update.effective_user and update.effective_user.id != DEV_ID:
        await update.message.reply_text("⛔ Команда доступна только разработчику.")
        return

    await update.message.reply_text("▶️ Запускаю тестовую рассылку (только dev)…")
    res = await run_update()
    details = res.get("details") or []
    
    # Фильтруем только значимые изменения
    meaningful_details = [d for d in details if _is_meaningful_change(d)]
    
    if not meaningful_details:
        msg = f"🟢 Всего изменений: {len(details)}\nЗначимых для таргетинга: 0\n\n🟢 Все изменения незначительные."
        await context.bot.send_message(chat_id=DEV_ID, text=msg, parse_mode="HTML")
        await update.message.reply_text("Готово: значимых изменений не было.")
        return

    sent = 0
    for d in meaningful_details:
        # Используем умное форматирование
        parts = format_change_smart(d)
        for p in parts:
            out = p
            if _needs_translation(out):
                try:
                    out = translate_compact_html(out, target_lang="ru", max_len=MAX_NOTIFY_CHARS)
                except Exception:
                    out = p
            out = _sanitize_telegram_html(out)
            await context.bot.send_message(chat_id=DEV_ID, text=out, parse_mode="HTML", disable_web_page_preview=True)
            # Задержка для избежания flood control
            await asyncio.sleep(0.05)
            sent += 1
    
    await update.message.reply_text(f"Готово: {len(details)} изменений, {len(meaningful_details)} значимых, {sent} сообщений отправлено.")

def setup_handlers(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("testdispatch", cmd_testdispatch))
    app.add_handler(CallbackQueryHandler(on_button))
