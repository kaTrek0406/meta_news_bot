#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика проблем с прокси в production Railway
"""

import os
import asyncio
import httpx
import sys
sys.path.append(os.path.dirname(__file__))

from src.pipeline import _get_proxy_for_region
from src.config import USE_PROXY, PROXY_URL, PROXY_URL_EU, PROXY_PROVIDER

async def debug_proxy_issue():
    print("🔍 ДИАГНОСТИКА ПРОКСИ В PRODUCTION")
    print("="*50)
    
    # 1. Проверяем переменные окружения
    print("1. Переменные окружения:")
    print(f"   USE_PROXY: {USE_PROXY}")
    print(f"   PROXY_PROVIDER: {PROXY_PROVIDER}")
    print(f"   PROXY_URL: {PROXY_URL[:50] if PROXY_URL else None}...")
    print(f"   PROXY_URL_EU: {PROXY_URL_EU[:50] if PROXY_URL_EU else None}...")
    
    # 2. Тестируем получение прокси
    print("\n2. Получение прокси конфигурации:")
    regions = ["GLOBAL", "EU", "MD"]
    
    for region in regions:
        try:
            proxy_config = _get_proxy_for_region(region, None, "debug_test")
            print(f"   {region}: {proxy_config}")
            
            if proxy_config:
                # Проверяем структуру
                http_proxy = proxy_config.get("http://", "НЕТ")
                https_proxy = proxy_config.get("https://", "НЕТ") 
                print(f"       HTTP:  {http_proxy[:60]}...")
                print(f"       HTTPS: {https_proxy[:60]}...")
        except Exception as e:
            print(f"   {region}: ОШИБКА - {e}")
    
    # 3. Тестируем реальное подключение через прокси
    print("\n3. Тестирование подключения:")
    
    proxy_config = _get_proxy_for_region("GLOBAL", None, "debug_test")
    if proxy_config:
        try:
            timeout = httpx.Timeout(10.0)
            async with httpx.AsyncClient(timeout=timeout, proxies=proxy_config, verify=False) as client:
                # Проверяем IP
                response = await client.get("https://httpbin.org/ip")
                ip_data = response.json()
                print(f"   IP через прокси: {ip_data}")
                
                # Проверяем Meta URL
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
                
                response = await client.get("https://transparency.meta.com/policies/ad-standards/?_fb_noscript=1", headers=headers)
                print(f"   Meta ответ: {response.status_code}, размер: {len(response.text)}")
                
                if response.status_code == 422 and len(response.text) > 1000:
                    print("   ✅ 422 с большим HTML - это OK!")
                else:
                    print(f"   ❌ Проблема: статус {response.status_code}, размер {len(response.text)}")
                    
        except Exception as e:
            print(f"   ❌ Ошибка подключения: {e}")
    else:
        print("   ❌ Прокси конфигурация не получена!")
    
    # 4. Проверяем без прокси для сравнения
    print("\n4. Тестирование БЕЗ прокси:")
    try:
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.get("https://httpbin.org/ip")
            ip_data = response.json()
            print(f"   IP без прокси: {ip_data}")
    except Exception as e:
        print(f"   Ошибка без прокси: {e}")
        
    print("\n" + "="*50)
    print("🔍 ДИАГНОСТИКА ЗАВЕРШЕНА")

if __name__ == "__main__":
    asyncio.run(debug_proxy_issue())