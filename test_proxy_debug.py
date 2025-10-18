#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Тест отладки прокси конфигурации
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from src.pipeline import _get_proxy_for_region
from src.config import validate_proxy_config

def main():
    print("🔍 Тестирование прокси конфигурации")
    print("=" * 50)
    
    # Проверяем общую конфигурацию
    print("📋 Проверка общей конфигурации:")
    validate_proxy_config()
    
    print("\n🌍 Тестирование прокси для разных регионов:")
    print("-" * 50)
    
    regions_to_test = [
        ("GLOBAL", None),
        ("EU", "de"),
        ("MD", "md"),
        ("EU", None),
        ("MD", None)
    ]
    
    for region, proxy_country in regions_to_test:
        print(f"\n🔹 Регион: {region}, proxy_country: {proxy_country}")
        
        proxy_config = _get_proxy_for_region(region, proxy_country, "test_session_123")
        
        if proxy_config:
            print(f"   ✅ Прокси настроен: {list(proxy_config.keys())}")
            for scheme, url in proxy_config.items():
                # Маскируем пароль для безопасности
                masked_url = url
                if "@" in url:
                    parts = url.split("@")
                    if ":" in parts[0]:
                        auth_part = parts[0]
                        # Показываем только первые 3 символа пароля
                        if "://" in auth_part:
                            scheme_part, creds = auth_part.split("://", 1)
                            if ":" in creds:
                                user, password = creds.split(":", 1)
                                masked_password = password[:3] + "***" + password[-3:] if len(password) > 6 else "***"
                                masked_url = f"{scheme_part}://{user}:{masked_password}@{parts[1]}"
                
                print(f"     {scheme}: {masked_url}")
        else:
            print("   ❌ Прокси НЕ настроен (None)")
    
    print("\n✅ Тест прокси конфигурации завершен!")

if __name__ == "__main__":
    main()