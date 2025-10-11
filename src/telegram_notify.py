# -*- coding: utf-8 -*-
import os
import httpx
import asyncio
import logging

log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DEV_CHAT_ID = os.getenv("TELEGRAM_DEV_CHAT_ID", "")  # новый
MAX_LEN = 3500

def _parse_ids(s: str):
    return [p.strip() for p in (s or "").split(",") if p.strip()]

async def _send(client: httpx.AsyncClient, chat_id: str, text: str):
    if not BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text.strip(),
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    await client.post(url, json=payload)

async def notify(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        return
    chunks = []
    while len(text) > MAX_LEN:
        split_idx = text[:MAX_LEN].rfind("\n")
        if split_idx == -1:
            split_idx = MAX_LEN
        chunks.append(text[:split_idx])
        text = text[split_idx:]
    chunks.append(text)

    ids = _parse_ids(CHAT_ID)
    async with httpx.AsyncClient(timeout=20) as client:
        for chunk in chunks:
            for cid in ids:
                try:
                    await _send(client, cid, chunk)
                    await asyncio.sleep(0.3)
                except Exception as e:
                    log.error(f"Не удалось отправить сообщение в Telegram: {e}")

async def notify_dev(text: str) -> None:
    cid = DEV_CHAT_ID or (_parse_ids(CHAT_ID)[0] if CHAT_ID else "")
    if not cid or not BOT_TOKEN:
        return
    chunks = []
    while len(text) > MAX_LEN:
        split_idx = text[:MAX_LEN].rfind("\n")
        if split_idx == -1:
            split_idx = MAX_LEN
        chunks.append(text[:split_idx])
        text = text[split_idx:]
    chunks.append(text)

    async with httpx.AsyncClient(timeout=20) as client:
        for chunk in chunks:
            try:
                await _send(client, cid, chunk)
                await asyncio.sleep(0.2)
            except Exception as e:
                log.error(f"Не удалось отправить dev-сообщение в Telegram: {e}")
