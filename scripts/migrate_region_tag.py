#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт миграции: добавляет region='GLOBAL' к записям в кэше, где его нет.

Проходит по:
- data/cache/cache.json
- data/items.json (если есть)

И добавляет поле "region": "GLOBAL" туда, где его нет.
Выводит отчёт в консоль.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "cache.json"
ITEMS_FILE = PROJECT_ROOT / "data" / "items.json"


def migrate_file(file_path: Path) -> tuple[int, int]:
    """
    Мигрирует файл: добавляет region='GLOBAL' где его нет.
    Возвращает (total_items, migrated_items).
    """
    if not file_path.exists():
        return 0, 0
    
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Ошибка чтения {file_path}: {e}")
        return 0, 0
    
    # Поддержка разных форматов
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "items" in data:
        items = data["items"]
    else:
        print(f"⚠️  Неизвестный формат файла {file_path}")
        return 0, 0
    
    if not isinstance(items, list):
        print(f"⚠️  items не является списком в {file_path}")
        return 0, 0
    
    total = len(items)
    migrated = 0
    
    for item in items:
        if isinstance(item, dict) and "region" not in item:
            item["region"] = "GLOBAL"
            migrated += 1
    
    if migrated > 0:
        # Сохраняем с изменениями
        try:
            tmp_file = file_path.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                if isinstance(data, list):
                    json.dump(items, f, ensure_ascii=False, indent=2)
                else:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, file_path)
            print(f"✅ {file_path.name}: добавлено region='GLOBAL' к {migrated} записям из {total}")
        except Exception as e:
            print(f"❌ Ошибка записи {file_path}: {e}")
            return total, 0
    else:
        print(f"ℹ️  {file_path.name}: все {total} записей уже имеют region")
    
    return total, migrated


def main():
    print("🚀 Миграция: добавление region='GLOBAL' к записям без region\n")
    
    total_all = 0
    migrated_all = 0
    
    # Миграция cache.json
    if CACHE_FILE.exists():
        print(f"📁 Обработка: {CACHE_FILE.relative_to(PROJECT_ROOT)}")
        t, m = migrate_file(CACHE_FILE)
        total_all += t
        migrated_all += m
    else:
        print(f"⚠️  Файл не найден: {CACHE_FILE.relative_to(PROJECT_ROOT)}")
    
    print()
    
    # Миграция items.json (если есть)
    if ITEMS_FILE.exists():
        print(f"📁 Обработка: {ITEMS_FILE.relative_to(PROJECT_ROOT)}")
        t, m = migrate_file(ITEMS_FILE)
        total_all += t
        migrated_all += m
    else:
        print(f"ℹ️  Файл не найден (необязательно): {ITEMS_FILE.relative_to(PROJECT_ROOT)}")
    
    print()
    print("=" * 60)
    print(f"📊 Итого обработано записей: {total_all}")
    print(f"✨ Мигрировано (добавлен region): {migrated_all}")
    print(f"✅ Уже имели region: {total_all - migrated_all}")
    print("=" * 60)
    
    if migrated_all > 0:
        print("\n✅ Миграция завершена успешно!")
    else:
        print("\nℹ️  Миграция не требовалась - все записи уже имеют region")


if __name__ == "__main__":
    main()
