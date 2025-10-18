#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Комплексная система тестирования Meta News Bot
Запускать перед каждым коммитом на GitHub
"""

import asyncio
import sys
import os
import json
import time
from typing import Dict, List, Tuple
sys.path.append(os.path.dirname(__file__))

import httpx
from src.pipeline import _get_proxy_for_region, _get_random_headers, _fix_facebook_url
from src.smart_formatter import group_changes_by_region, format_region_summary
from src.config import validate_proxy_config

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []
    
    def pass_test(self, name: str):
        print(f"[+] {name}")
        self.passed += 1
    
    def fail_test(self, name: str, error: str):
        print(f"[-] {name}: {error}")
        self.failed += 1
        self.errors.append(f"{name}: {error}")
    
    def warn_test(self, name: str, warning: str):
        print(f"[!] {name}: {warning}")
        self.warnings += 1
    
    def summary(self):
        print("\n" + "="*60)
        print("[RESULTS] РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
        print("="*60)
        print(f"[+] Пройдено: {self.passed}")
        print(f"[-] Провалено: {self.failed}")
        print(f"[!] Предупреждений: {self.warnings}")
        
        if self.failed > 0:
            print(f"\n[!] ОШИБКИ:")
            for error in self.errors:
                print(f"  • {error}")
            return False
        else:
            print(f"\n[OK] ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
            return True

async def test_config_validation(results: TestResults):
    """Тест 1: Проверка конфигурации"""
    print("\n[1] Тест 1: Проверка конфигурации")
    print("-" * 40)
    
    try:
        # Проверяем прокси конфигурацию
        validate_proxy_config()
        results.pass_test("Прокси конфигурация валидна")
    except Exception as e:
        results.fail_test("Прокси конфигурация", str(e))
    
    # Проверяем источники в config.json
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        
        sources = config.get("sources", [])
        if len(sources) == 0:
            results.fail_test("Источники в config.json", "Нет источников")
        else:
            results.pass_test(f"Источники загружены ({len(sources)} шт.)")
        
        # Проверяем региональные источники
        regions = {}
        for source in sources:
            region = source.get("region", "GLOBAL")
            regions[region] = regions.get(region, 0) + 1
        
        required_regions = ["MD", "EU", "GLOBAL"]
        for region in required_regions:
            if region in regions:
                results.pass_test(f"Источники для региона {region} ({regions[region]} шт.)")
            else:
                results.warn_test(f"Регион {region}", "Нет источников")
    
    except Exception as e:
        results.fail_test("config.json", str(e))

async def test_proxy_functionality(results: TestResults):
    """Тест 2: Проверка прокси для разных регионов"""
    print("\n[2] Тест 2: Функциональность прокси")
    print("-" * 40)
    
    test_regions = [
        ("GLOBAL", None),
        ("EU", "de"), 
        ("MD", "md")
    ]
    
    for region, proxy_country in test_regions:
        try:
            proxy_config = _get_proxy_for_region(region, proxy_country, "test_session")
            if proxy_config:
                results.pass_test(f"Прокси для {region} настроен")
            else:
                results.warn_test(f"Прокси для {region}", "Не настроен (возможно USE_PROXY=0)")
        except Exception as e:
            results.fail_test(f"Прокси для {region}", str(e))

async def test_headers_generation(results: TestResults):
    """Тест 3: Генерация заголовков"""
    print("\n[3] Тест 3: Генерация заголовков")
    print("-" * 40)
    
    test_urls = [
        "https://transparency.meta.com/policies/ad-standards/",
        "https://developers.facebook.com/docs/marketing-api/",
        "https://business.whatsapp.com/policy",
        "https://metastatus.com/"
    ]
    
    for url in test_urls:
        try:
            headers = _get_random_headers(url, "en-US,en;q=0.9")
            
            # Проверяем обязательные заголовки
            required = ["User-Agent", "Accept", "Accept-Language"]
            for header in required:
                if header not in headers:
                    results.fail_test(f"Заголовки для {url}", f"Отсутствует {header}")
                    break
            else:
                results.pass_test(f"Заголовки для {url}")
                
                # Проверяем специальную обработку для Meta сайтов
                if any(domain in url for domain in ["facebook.com", "transparency.meta.com"]):
                    if "Referer" in headers:
                        results.pass_test(f"Meta-специфичные заголовки для {url}")
                    else:
                        results.warn_test(f"Meta заголовки для {url}", "Referer не добавлен")
        
        except Exception as e:
            results.fail_test(f"Заголовки для {url}", str(e))

async def test_url_processing(results: TestResults):
    """Тест 4: Обработка URL"""
    print("\n[4] Тест 4: Обработка URL")
    print("-" * 40)
    
    test_cases = [
        ("https://transparency.meta.com/policies/ad-standards/", 
         "https://transparency.meta.com/policies/ad-standards/?_fb_noscript=1"),
        ("https://developers.facebook.com/docs/marketing-api/", 
         "https://developers.facebook.com/docs/marketing-api/?_fb_noscript=1"),
        ("https://metastatus.com/", 
         "https://metastatus.com/")  # Не должен изменяться
    ]
    
    for original, expected in test_cases:
        try:
            processed = _fix_facebook_url(original)
            if processed == expected:
                results.pass_test(f"URL обработка: {original}")
            else:
                results.fail_test(f"URL обработка: {original}", f"Ожидался {expected}, получен {processed}")
        except Exception as e:
            results.fail_test(f"URL обработка: {original}", str(e))

async def test_regional_grouping(results: TestResults):
    """Тест 5: Региональная группировка"""
    print("\n[5] Тест 5: Региональная группировка")
    print("-" * 40)
    
    # Тестовые данные
    test_details = [
        {"title": "Global Policy", "region": "GLOBAL", "global_diff": {"changed": [], "added": ["test"], "removed": []}},
        {"title": "EU Restriction", "region": "EU", "global_diff": {"changed": [], "added": ["eu test"], "removed": []}},
        {"title": "Moldova Rule", "region": "MD", "global_diff": {"changed": [], "added": ["md test"], "removed": []}},
        {"title": "Another MD Rule", "region": "MD", "global_diff": {"changed": [], "added": ["md test 2"], "removed": []}}
    ]
    
    try:
        # Тестируем группировку
        grouped = group_changes_by_region(test_details)
        
        expected_regions = {"GLOBAL": 1, "EU": 1, "MD": 2}
        if set(grouped.keys()) == set(expected_regions.keys()):
            results.pass_test("Группировка по регионам")
        else:
            results.fail_test("Группировка по регионам", f"Ожидались регионы {list(expected_regions.keys())}, получены {list(grouped.keys())}")
        
        # Тестируем форматирование
        for region, details in grouped.items():
            try:
                formatted = format_region_summary(region, details)
                if formatted and len(formatted) > 0:
                    results.pass_test(f"Форматирование для {region}")
                else:
                    results.fail_test(f"Форматирование для {region}", "Пустой результат")
            except Exception as e:
                results.fail_test(f"Форматирование для {region}", str(e))
    
    except Exception as e:
        results.fail_test("Региональная группировка", str(e))

async def test_http_request(results: TestResults):
    """Тест 6: HTTP запрос с обработкой 422"""
    print("\n[6] Тест 6: HTTP запросы")
    print("-" * 40)
    
    # Быстрый тест одного источника - Meta сайт может возвращать 422
    url = "https://transparency.meta.com/policies/ad-standards/"
    try:
        processed_url = _fix_facebook_url(url)
        proxy_config = _get_proxy_for_region("GLOBAL", None, "test_session")
        headers = _get_random_headers(processed_url, "en-US,en;q=0.9")
        
        timeout = httpx.Timeout(15.0, connect=10.0)  # Короче таймаут для теста
        verify_ssl = proxy_config is None
        
        # Проверяем что компоненты работают
        if proxy_config:
            results.pass_test("HTTP компоненты: прокси настроен")
        if headers:
            results.pass_test("HTTP компоненты: заголовки сгенерированы")
        if processed_url != url:
            results.pass_test("HTTP компоненты: URL обработан")
        
        # Пробуем реальный запрос, но принимаем любой результат
        start_time = time.time()
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                proxies=proxy_config,
                verify=verify_ssl
            ) as client:
                response = await client.get(processed_url, headers=headers)
                duration = time.time() - start_time
                results.pass_test(f"HTTP запрос: {response.status_code}, {len(response.text)} симв., {duration:.1f}с")
        
        except Exception as e:
            duration = time.time() - start_time
            # Любое исключение считаем ожидаемым поведением для Meta сайтов
            if "422" in str(e) or "Unprocessable Entity" in str(e):
                results.pass_test(f"HTTP запрос: 422 (ожидаемо для Meta), {duration:.1f}с")
            else:
                results.warn_test("HTTP запрос", f"Неожиданная ошибка: {str(e)[:100]}")
    
    except Exception as e:
        results.fail_test("HTTP запрос", str(e))

async def run_all_tests():
    """Запускает все тесты"""
    print("[TEST] ЗАПУСК КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ META NEWS BOT")
    print("="*60)
    print("Проверяем все компоненты перед коммитом...")
    
    results = TestResults()
    
    # Запускаем все тесты
    await test_config_validation(results)
    await test_proxy_functionality(results)
    await test_headers_generation(results)
    await test_url_processing(results)
    await test_regional_grouping(results)
    await test_http_request(results)
    
    # Показываем итоговые результаты
    success = results.summary()
    
    if success:
        print("\n[OK] ГОТОВО К КОММИТУ!")
        print("Все тесты прошли успешно. Можно делать git commit.")
    else:
        print("\n[!] НЕ ГОТОВО К КОММИТУ!")
        print("Исправьте ошибки перед коммитом на GitHub.")
    
    return success

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)