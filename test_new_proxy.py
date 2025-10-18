#!/usr/bin/env python3
"""
Тестирование нового Froxy прокси для Meta News Bot.
Проверяет подключение к новому прокси и доступность Meta сайтов.
"""

import asyncio
import httpx
import time
from datetime import datetime

# Новый прокси Froxy
NEW_PROXY = "http://SakkTDU3kVHpEtNr:wifi;md;;;@proxy.froxy.com:9000"
EU_PROXY = "http://SakkTDU3kVHpEtNr:wifi;de;;;@proxy.froxy.com:9000"

# Тестовые URL Meta
TEST_URLS = [
    "https://transparency.meta.com/policies/ad-standards/",
    "https://www.facebook.com/business/help/298000447747885",
    "https://developers.facebook.com/docs/marketing-api/marketing-api-changelog/",
    "https://metastatus.com/",
    "https://business.whatsapp.com/policy",
]

# GEO тестирование
GEO_TEST_URL = "http://httpbin.org/ip"

def get_random_headers():
    """Генерирует заголовки для запроса"""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ro;q=0.8,ru;q=0.7",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

async def test_proxy(proxy_url: str, region: str):
    """Тестирует прокси сервер"""
    print(f"\n🔍 Тестирование прокси для региона {region}")
    print(f"Прокси: {proxy_url.split('@')[1] if '@' in proxy_url else proxy_url}")
    print("=" * 50)
    
    proxies = {"http://": proxy_url, "https://": proxy_url}
    headers = get_random_headers()
    timeout = httpx.Timeout(30.0, connect=15.0)
    
    # 1. Проверка IP адреса через прокси
    try:
        async with httpx.AsyncClient(proxies=proxies, timeout=timeout, verify=False) as client:
            print("🌐 Проверяем IP адрес через прокси...")
            response = await client.get(GEO_TEST_URL, headers=headers)
            response.raise_for_status()
            ip_info = response.json()
            print(f"✅ IP: {ip_info.get('origin', 'N/A')}")
    except Exception as e:
        print(f"❌ Ошибка получения IP: {e}")
        return False
    
    # 2. Тестирование Meta URL
    success_count = 0
    for i, url in enumerate(TEST_URLS, 1):
        try:
            print(f"\n📋 {i}/{len(TEST_URLS)} Тестируем: {url}")
            
            start_time = time.time()
            async with httpx.AsyncClient(proxies=proxies, timeout=timeout, verify=False) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                content = response.text
                
                # Проверяем на блокировку
                if "You're Temporarily Blocked" in content or "going too fast" in content:
                    print(f"⚠️  Временная блокировка Facebook")
                    continue
                elif "407 Proxy Authentication Required" in content:
                    print(f"❌ 407 Proxy Authentication Required")
                    continue
                    
                load_time = time.time() - start_time
                print(f"✅ Успешно загружено за {load_time:.2f}с (размер: {len(content)} символов)")
                success_count += 1
                
                # Задержка между запросами
                if i < len(TEST_URLS):
                    await asyncio.sleep(2)
                    
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP ошибка {e.response.status_code}: {url}")
        except Exception as e:
            print(f"❌ Ошибка: {str(e)[:100]}")
    
    print(f"\n📊 Результат для {region}: {success_count}/{len(TEST_URLS)} успешных запросов")
    return success_count > 0

async def main():
    """Главная функция тестирования"""
    print("🚀 Тестирование нового Froxy прокси для Meta News Bot")
    print(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Тестируем молдавский прокси
    md_success = await test_proxy(NEW_PROXY, "MD (Молдова)")
    
    # Небольшая пауза
    await asyncio.sleep(5)
    
    # Тестируем европейский прокси
    eu_success = await test_proxy(EU_PROXY, "EU (Европа)")
    
    print("\n" + "=" * 60)
    print("📋 ИТОГОВЫЙ ОТЧЁТ:")
    print(f"🇲🇩 Молдавский прокси: {'✅ Работает' if md_success else '❌ Не работает'}")
    print(f"🇪🇺 Европейский прокси: {'✅ Работает' if eu_success else '❌ Не работает'}")
    
    if md_success or eu_success:
        print("\n✅ Прокси настроен правильно! Бот сможет обходить блокировки.")
        print("🚀 Можно деплоить на Railway.")
    else:
        print("\n❌ Проблемы с прокси! Нужно проверить настройки:")
        print("• Проверьте логин/пароль")
        print("• Убедитесь что в аккаунте Froxy есть средства") 
        print("• Попробуйте другой формат подключения")
    
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())