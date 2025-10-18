#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Тест региональной группировки изменений
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from src.smart_formatter import group_changes_by_region, format_region_summary

# Тестовые данные с изменениями для разных регионов
test_details = [
    {
        "title": "Updated Ad Standards Policy", 
        "url": "https://transparency.meta.com/policies/ad-standards/",
        "region": "GLOBAL",
        "global_diff": {
            "changed": [{"was": "Old policy text", "now": "New policy text with restrictions"}],
            "added": ["New restriction for political ads"],
            "removed": []
        }
    },
    {
        "title": "EU Political Ads Restrictions", 
        "url": "https://transparency.meta.com/policies/ad-standards/siep-advertising/siep",
        "region": "EU",
        "global_diff": {
            "changed": [{"was": "Basic EU rules", "now": "Enhanced SIEP requirements"}],
            "added": ["Stricter verification for political advertisers"],
            "removed": ["Old exemptions"]
        }
    },
    {
        "title": "Moldova-specific Ad Standards", 
        "url": "https://transparency.meta.com/policies/ad-standards/",
        "region": "MD",
        "global_diff": {
            "changed": [{"was": "General standards", "now": "Moldova-specific requirements"}],
            "added": ["Local language requirements", "Regional compliance rules"],
            "removed": []
        }
    },
    {
        "title": "API Changelog for Moldova", 
        "url": "https://developers.facebook.com/docs/marketing-api/marketing-api-changelog/",
        "region": "MD",
        "global_diff": {
            "changed": [],
            "added": ["New Moldova region targeting field"],
            "removed": []
        }
    }
]

def main():
    print("🧪 Тестирование региональной группировки")
    print("=" * 50)
    
    # Группируем изменения по регионам
    grouped = group_changes_by_region(test_details)
    
    print(f"📊 Обнаружено регионов: {len(grouped)}")
    for region, details in grouped.items():
        print(f"  • {region}: {len(details)} изменений")
    
    print("\n🏷️ Форматирование по регионам:")
    print("=" * 50)
    
    # Форматируем каждый регион
    for region in sorted(grouped.keys()):
        region_details = grouped[region]
        print(f"\n🔹 Регион: {region} ({len(region_details)} изменений)")
        
        # Форматируем сводку
        summary_parts = format_region_summary(region, region_details)
        
        for i, part in enumerate(summary_parts, 1):
            print(f"\n--- Часть {i} ---")
            print(part)
    
    print("\n✅ Тест региональной группировки завершен!")

if __name__ == "__main__":
    main()