# -*- coding: utf-8 -*-
"""
Модуль для резервного копирования кэша в GitHub Gist.
Используется для бесплатных планов Railway без Volumes.
"""
import os
import json
import logging
import requests
from typing import Optional

log = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_BACKUP_TOKEN", "")
GIST_ID = os.getenv("GITHUB_GIST_ID", "")
BACKUP_ENABLED = GITHUB_TOKEN and GIST_ID

def backup_to_gist(data: dict) -> bool:
    """Сохраняет кэш в GitHub Gist"""
    if not BACKUP_ENABLED:
        return False
    
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        payload = {
            "files": {
                "cache.json": {
                    "content": json.dumps(data, ensure_ascii=False, indent=2)
                }
            }
        }
        
        response = requests.patch(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        log.info("✅ Кэш успешно сохранён в GitHub Gist")
        return True
    except Exception as e:
        log.error(f"❌ Ошибка сохранения в Gist: {e}")
        return False

def restore_from_gist() -> Optional[dict]:
    """Восстанавливает кэш из GitHub Gist"""
    if not BACKUP_ENABLED:
        return None
    
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        gist_data = response.json()
        cache_file = gist_data.get("files", {}).get("cache.json", {})
        content = cache_file.get("content", "{}")
        
        data = json.loads(content)
        log.info("✅ Кэш успешно восстановлен из GitHub Gist")
        return data
    except Exception as e:
        log.error(f"❌ Ошибка восстановления из Gist: {e}")
        return None
