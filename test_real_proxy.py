#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест для проверки работы прокси в production Railway
"""

import asyncio
import httpx
import os
import sys
sys.path.append(os.path.dirname(__file__))

from src.pipeline import _get_proxy_for_region

async def test_real_ip():
    print("🌐 ПРОВЕРКА РЕАЛЬНОГО IP В RAILWAY")
    print("="*50)
    
    # Переменные окружения
    os.environ["USE_PROXY"] = "1"
    os.environ["PROXY_PROVIDER"] = "froxy"
    os.environ["PROXY_URL"] = "http://SakkTDU3kVHpEtNr:wifi;md;;;@proxy.froxy.com:9000"
    
    # 1. IP без прокси
    print("\n1. IP БЕЗ ПРОКСИ:")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get("https://httpbin.org/ip")
            data = r.json()
            print(f"   IP: {data.get('origin')}")
            print(f"   Статус: {r.status_code}")
    except Exception as e:
        print(f"   Ошибка: {e}")
    
    # 2. IP через наш прокси
    print("\n2. IP ЧЕРЕЗ НАШ ПРОКСИ:")
    try:
        proxies = _get_proxy_for_region("GLOBAL", None, "test_real")
        if proxies:
            print(f"   Прокси конфиг: {proxies}")
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), proxies=proxies, verify=False) as client:
                r = await client.get("https://httpbin.org/ip")
                data = r.json()
                print(f"   IP через прокси: {data.get('origin')}")
                print(f"   Статус: {r.status_code}")
                
                # Проверим гео
                try:
                    geo_r = await client.get("https://ipapi.co/json/")
                    geo_data = geo_r.json()
                    print(f"   Страна: {geo_data.get('country_name')} ({geo_data.get('country_code')})")
                    print(f"   Регион: {geo_data.get('region')}")
                except:
                    print("   Гео информация недоступна")
        else:
            print("   Прокси не настроен!")
    except Exception as e:
        print(f"   Ошибка через прокси: {e}")
    
    # 3. Тест Meta URL
    print("\n3. ТЕСТ META URL:")
    test_urls = [
        "https://transparency.meta.com/policies/ad-standards/?_fb_noscript=1"
    ]
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n   {i}. Тестируем: {url}")
        
        # Без прокси
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                r = await client.get(url)
                print(f"      БЕЗ прокси: {r.status_code}, {len(r.text)} символов")
        except Exception as e:
            print(f"      БЕЗ прокси: ОШИБКА - {e}")
        
        # С прокси
        try:
            proxies = _get_proxy_for_region("GLOBAL", None, "test_meta")
            if proxies:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), proxies=proxies, verify=False) as client:
                    r = await client.get(url)
                    print(f"      С прокси: {r.status_code}, {len(r.text)} символов")
        except Exception as e:
            print(f"      С прокси: ОШИБКА - {e}")
    
    print("\n" + "="*50)
    print("🌐 ТЕСТ IP ЗАВЕРШЕН")

if __name__ == "__main__":
    asyncio.run(test_real_ip())