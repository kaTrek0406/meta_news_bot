#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Тест одного источника для проверки обработки 422 ошибок
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(__file__))

import httpx
from src.pipeline import _get_proxy_for_region, _get_random_headers, _fix_facebook_url

async def test_single_source():
    """Тестируем один источник с нашими улучшениями"""
    
    # Тестовый URL
    url = "https://transparency.meta.com/policies/ad-standards/"
    region = "GLOBAL"
    
    print(f"🧪 Тестирование источника: {url}")
    print(f"🌍 Регион: {region}")
    print("=" * 50)
    
    # Обрабатываем URL
    processed_url = _fix_facebook_url(url)
    print(f"📋 Обработанный URL: {processed_url}")
    
    # Получаем прокси
    proxy_config = _get_proxy_for_region(region, None, "test_session")
    if proxy_config:
        print(f"🔐 Прокси: {list(proxy_config.keys())}")
    else:
        print("❌ Прокси не настроен")
    
    # Получаем заголовки
    headers = _get_random_headers(processed_url, "en-US,en;q=0.9")
    print(f"📡 User-Agent: {headers.get('User-Agent', 'N/A')[:80]}...")
    print(f"📡 Accept: {headers.get('Accept', 'N/A')}")
    print(f"📡 Referer: {headers.get('Referer', 'N/A')}")
    
    print("\n🚀 Выполняем запрос...")
    
    timeout = httpx.Timeout(30.0, connect=15.0)
    verify_ssl = proxy_config is None
    
    try:
        async with httpx.AsyncClient(
            timeout=timeout, 
            follow_redirects=True, 
            proxies=proxy_config, 
            verify=verify_ssl
        ) as client:
            
            response = await client.get(processed_url, headers=headers)
            
            print(f"📊 Status Code: {response.status_code}")
            print(f"📊 Content Length: {len(response.text)} символов")
            
            if response.status_code == 422:
                if response.text and len(response.text.strip()) > 100:
                    print("✅ 422 статус с валидным содержимым - ПРИНИМАЕМ")
                    content_preview = response.text[:200] + "..." if len(response.text) > 200 else response.text
                    print(f"📄 Превью содержимого: {content_preview}")
                else:
                    print("❌ 422 статус с коротким содержимым - ОТКЛОНЯЕМ")
            elif response.status_code in [200, 201, 202]:
                print("✅ Успешный статус код")
                content_preview = response.text[:200] + "..." if len(response.text) > 200 else response.text
                print(f"📄 Превью содержимого: {content_preview}")
            else:
                print(f"⚠️ Неожиданный статус код: {response.status_code}")
                
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")

if __name__ == "__main__":
    asyncio.run(test_single_source())