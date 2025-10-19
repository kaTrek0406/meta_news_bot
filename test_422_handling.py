#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Специальный тест обработки 422 статуса для Meta сайтов
"""

import os
import asyncio
import httpx
import sys
sys.path.append(os.path.dirname(__file__))

from src.pipeline import _get_proxy_for_region, _get_random_headers, _fix_facebook_url

async def test_422_handling():
    print("🧪 ТЕСТИРОВАНИЕ ОБРАБОТКИ 422 СТАТУСА")
    print("="*50)
    
    # Настроим переменные окружения
    os.environ["USE_PROXY"] = "1"
    os.environ["PROXY_PROVIDER"] = "froxy"
    os.environ["PROXY_URL"] = "http://SakkTDU3kVHpEtNr:wifi;md;;;@proxy.froxy.com:9000"
    
    # Тестовые Meta URL
    test_urls = [
        "https://transparency.meta.com/policies/ad-standards/",
        "https://transparency.meta.com/policies/ad-standards/restricted-goods-services/drugs-pharmaceuticals"
    ]
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n{i}. Тестируем URL: {url}")
        
        # Обработка URL
        processed_url = _fix_facebook_url(url)
        print(f"   Обработанный URL: {processed_url}")
        
        # Получение прокси
        proxies = _get_proxy_for_region("GLOBAL", None, "test_422")
        if proxies:
            proxy_info = proxies.get('https://') or proxies.get('http://', '')
            safe_proxy = proxy_info.split('@')[-1] if '@' in proxy_info else proxy_info
            print(f"   Прокси: {safe_proxy}")
        
        # Заголовки
        headers = _get_random_headers(processed_url, "en-US,en;q=0.9")
        
        # HTTP запрос - точно так же как в pipeline
        try:
            timeout = httpx.Timeout(15.0)
            async with httpx.AsyncClient(timeout=timeout, proxies=proxies, verify=False) as client:
                try:
                    response = await client.get(processed_url, headers=headers)
                    print(f"   Статус: {response.status_code}")
                    print(f"   Размер ответа: {len(response.text)} символов")
                    
                    # Точно та же логика как в pipeline
                    html = None
                    if response.status_code == 422:
                        is_meta_site = any(domain in processed_url for domain in ["transparency.meta.com", "facebook.com", "about.fb.com", "developers.facebook.com"])
                        if is_meta_site and response.text and len(response.text.strip()) > 100:
                            print(f"   ✅ Meta сайт: Статус 422 но получен HTML ({len(response.text)} симв.), продолжаем")
                            html = response.text
                        elif response.text and len(response.text.strip()) > 500:
                            print(f"   ✅ Статус 422 но получен валидный HTML ({len(response.text)} симв.), продолжаем")
                            html = response.text
                        else:
                            print(f"   ⚠️ Статус 422 с коротким ответом ({len(response.text) if response.text else 0} симв.), ошибка!")
                            response.raise_for_status()
                    elif response.status_code in [200, 201, 202]:
                        html = response.text
                        print(f"   ✅ Успешный статус: {response.status_code}")
                    else:
                        response.raise_for_status()
                        html = response.text
                    
                    if html:
                        # Проверим содержимое
                        if "Transparency Center" in html:
                            print("   ✅ Контент Meta Transparency Center обнаружен")
                        elif "blocked" in html.lower() or "error" in html.lower():
                            print("   ❌ Возможная блокировка или ошибка в контенте")
                        else:
                            print("   ✅ HTML получен и готов для обработки")
                    else:
                        print("   ❌ HTML не получен")
                
                except httpx.HTTPStatusError as e:
                    print(f"   ⚠️ HTTP ошибка поймана: {e}")
                    if hasattr(e, 'response') and e.response and e.response.text:
                        print(f"      Статус: {e.response.status_code}")
                        print(f"      Размер: {len(e.response.text)} символов")
                        if e.response.status_code == 422 and len(e.response.text) > 1000:
                            print("      ✅ Но это 422 с HTML - будет обработано как успех в pipeline!")
                    
        except httpx.HTTPStatusError as e:
            print(f"   ❌ HTTP ошибка: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"      Статус: {e.response.status_code}")
                print(f"      Размер: {len(e.response.text)} символов")
        except Exception as e:
            print(f"   ❌ Общая ошибка: {e}")
    
    print("\n" + "="*50)
    print("🧪 ТЕСТ ЗАВЕРШЕН")

if __name__ == "__main__":
    asyncio.run(test_422_handling())