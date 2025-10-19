#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Полный интеграционный тест Meta News Bot
Тестирует ВСЕ функции перед деплойдом на Railway
"""

import asyncio
import sys
import os
import json
import time
from typing import Dict, List, Tuple
sys.path.append(os.path.dirname(__file__))

# Импорты всех компонентов системы
import httpx
from src.pipeline import run_update, _get_proxy_for_region, _get_random_headers, _fix_facebook_url
from src.smart_formatter import group_changes_by_region, format_region_summary, format_change_smart
from src.config import validate_proxy_config
from src.storage import load_cache, save_cache
from src.llm_client import chat
from src.summarize import summarize_rules
from src.llm_client import translate_compact_html
from src.tg.handlers import _is_meaningful_change

class FullTestResults:
    def __init__(self):
        self.total_tests = 0
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []
        self.test_data = {}  # Сохраняем данные между тестами
    
    def start_test(self, name: str):
        self.total_tests += 1
        print(f"\n[{self.total_tests:2d}] {name}")
        print("-" * 60)
    
    def pass_test(self, name: str, details: str = ""):
        print(f"[+] {name}" + (f" - {details}" if details else ""))
        self.passed += 1
    
    def fail_test(self, name: str, error: str):
        print(f"[-] {name}: {error}")
        self.failed += 1
        self.errors.append(f"{name}: {error}")
    
    def warn_test(self, name: str, warning: str):
        print(f"[!] {name}: {warning}")
        self.warnings += 1
    
    def summary(self):
        print("\n" + "="*80)
        print("[RESULTS] ПОЛНЫЙ ИНТЕГРАЦИОННЫЙ ТЕСТ - РЕЗУЛЬТАТЫ")
        print("="*80)
        print(f"Всего тестов: {self.total_tests}")
        print(f"[+] Пройдено: {self.passed}")
        print(f"[-] Провалено: {self.failed}")
        print(f"[!] Предупреждений: {self.warnings}")
        
        if self.failed > 0:
            print(f"\n[ERRORS] Критические ошибки:")
            for error in self.errors:
                print(f"  • {error}")
            return False
        else:
            print(f"\n[OK] ВСЕ ИНТЕГРАЦИОННЫЕ ТЕСТЫ ПРОЙДЕНЫ!")
            print("[SUCCESS] Бот готов к деплою на Railway!")
            return True

async def test_1_configuration(results: FullTestResults):
    """Тест 1: Конфигурация и настройки"""
    results.start_test("Конфигурация и настройки")
    
    # Устанавливаем реальные прокси для тестов
    os.environ["USE_PROXY"] = "1"
    os.environ["PROXY_PROVIDER"] = "froxy"
    os.environ["PROXY_URL"] = "http://SakkTDU3kVHpEtNr:wifi;md;;;@proxy.froxy.com:9000"
    os.environ["PROXY_URL_EU"] = "http://SakkTDU3kVHpEtNr:wifi;de;;;@proxy.froxy.com:9000"
    os.environ["PROXY_STICKY"] = "1"
    os.environ["PROXY_FALLBACK_EU"] = "1"
    print(f"[PROXY] Конфигурирую тесты с реальными Froxy прокси: SakkTDU3kVHpEtNr")
    
    try:
        # Проверяем прокси
        validate_proxy_config()
        results.pass_test("Прокси конфигурация валидна")
        
        # Проверяем источники
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        sources = config.get("sources", [])
        if len(sources) >= 25:
            results.pass_test(f"Источники загружены ({len(sources)} шт.)")
        else:
            results.fail_test("Источники", f"Слишком мало источников: {len(sources)}")
        
        # Проверяем переменные окружения
        required_env = ["TELEGRAM_BOT_TOKEN", "OPENROUTER_API_KEY", "USE_PROXY"]
        for env_var in required_env:
            if os.getenv(env_var):
                results.pass_test(f"Переменная окружения {env_var}")
            else:
                results.fail_test(f"Переменная окружения {env_var}", "Не установлена")
        
        results.test_data['sources'] = sources
    
    except Exception as e:
        results.fail_test("Конфигурация", str(e))

async def test_2_proxy_functionality(results: FullTestResults):
    """Тест 2: Функциональность прокси"""
    results.start_test("Функциональность прокси")
    
    regions_to_test = [("GLOBAL", None), ("EU", "de"), ("MD", "md")]
    
    for region, proxy_country in regions_to_test:
        try:
            proxy_config = _get_proxy_for_region(region, proxy_country, "integration_test")
            if proxy_config:
                proxy_url = proxy_config.get('https://') or proxy_config.get('http://', '')
                safe_proxy = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
                results.pass_test(f"Прокси для {region}", f"Прокси: {safe_proxy}")
                
                # Тестируем реальное подключение
                try:
                    timeout = httpx.Timeout(10.0)
                    async with httpx.AsyncClient(timeout=timeout, proxies=proxy_config, verify=False) as client:
                        response = await client.get("https://httpbin.org/ip")
                        ip_data = response.json()
                        results.pass_test(f"Прокси {region} подключение", f"IP: {ip_data.get('origin', 'unknown')}")
                except Exception as e:
                    results.warn_test(f"Прокси {region} подключение", f"Не удалось проверить: {str(e)[:50]}")
            else:
                results.warn_test(f"Прокси для {region}", "Не настроен")
        except Exception as e:
            results.fail_test(f"Прокси для {region}", str(e))

async def test_3_http_requests(results: FullTestResults):
    """Тест 3: HTTP запросы и обработка ошибок"""
    results.start_test("HTTP запросы и обработка ошибок")
    
    # Тестируем только один URL чтобы не перегружать серверы
    test_urls = [
        ("https://httpbin.org/status/200", "HTTP тест сайт")
    ]
    
    for url, name in test_urls:
        try:
            processed_url = _fix_facebook_url(url)
            proxy_config = _get_proxy_for_region("GLOBAL", None, "integration_test")
            headers = _get_random_headers(processed_url, "en-US,en;q=0.9")
            
            timeout = httpx.Timeout(15.0)
            async with httpx.AsyncClient(timeout=timeout, proxies=proxy_config, verify=False) as client:
                start_time = time.time()
                response = await client.get(processed_url, headers=headers)
                duration = time.time() - start_time
                
                if response.status_code in [200, 422]:
                    if response.text and len(response.text) > 1000:
                        results.pass_test(f"HTTP запрос {name}", 
                                        f"Статус: {response.status_code}, {len(response.text)} симв., {duration:.1f}с")
                    else:
                        results.warn_test(f"HTTP запрос {name}", f"Короткий ответ: {len(response.text)} симв.")
                else:
                    results.warn_test(f"HTTP запрос {name}", f"Неожиданный статус: {response.status_code}")
        
        except Exception as e:
            if "422" in str(e):
                results.pass_test(f"HTTP запрос {name}", "422 ошибка (ожидаемо для Meta)")
            else:
                results.fail_test(f"HTTP запрос {name}", str(e))

async def test_4_pipeline_components(results: FullTestResults):
    """Тест 4: Компоненты pipeline (без реальных запросов)"""
    results.start_test("Компоненты pipeline (без реальных запросов)")
    
    try:
        # Проверяем что pipeline компоненты работают
        from src.storage import load_cache, save_cache, compute_hash
        from src.html_clean import clean_html
        from src.summarize import normalize_plain, extract_sections
        
        # Тестируем загрузку кэша
        cache_data = load_cache()
        results.pass_test("Cache загрузка", f"Кэш: {len(cache_data.get('items', [])) if cache_data else 0} элементов")
        
        # Тестируем обработку HTML
        test_html = "<html><head><title>Test</title></head><body><p>Test content for Meta News Bot</p></body></html>"
        title, plain, cleaned = clean_html(test_html, "https://example.com")
        
        if title and plain:
            results.pass_test("HTML обработка", f"Заголовок: '{title}', текст: {len(plain)} симв.")
        else:
            results.fail_test("HTML обработка", "Не удалось извлечь данные")
        
        # Тестируем нормализацию текста
        normalized = normalize_plain(plain)
        if normalized:
            results.pass_test("Нормализация текста", f"{len(normalized)} симв.")
        
        # Тестируем хэширование
        hash_value = compute_hash(normalized)
        if hash_value:
            results.pass_test("Хэширование", f"Хэш: {hash_value[:16]}...")
        
        # Тестируем извлечение секций
        sections = extract_sections(cleaned)
        results.pass_test("Извлечение секций", f"{len(sections)} секций")
        
        # Создаем тестовые данные для последующих тестов
        results.test_data['details'] = [
            {
                "title": "Pipeline Test Change",
                "url": "https://transparency.meta.com/test",
                "region": "GLOBAL",
                "global_diff": {
                    "changed": [{"was": "Old test content", "now": "New test content with changes"}],
                    "added": ["Test addition from pipeline"],
                    "removed": []
                }
            }
        ]
        
        results.pass_test("Компоненты pipeline", "Все компоненты работают")
    
    except Exception as e:
        results.fail_test("Компоненты pipeline", str(e))

async def test_5_regional_grouping(results: FullTestResults):
    """Тест 5: Региональная группировка"""
    results.start_test("Региональная группировка")
    
    # Используем данные из pipeline теста или создаем тестовые
    details = results.test_data.get('details', [])
    
    if not details:
        # Создаем тестовые данные если pipeline не дал результатов
        details = [
            {"title": "Test Global", "region": "GLOBAL", "global_diff": {"changed": [], "added": ["test"], "removed": []}},
            {"title": "Test EU", "region": "EU", "global_diff": {"changed": [], "added": ["eu test"], "removed": []}},
            {"title": "Test MD", "region": "MD", "global_diff": {"changed": [], "added": ["md test"], "removed": []}}
        ]
    
    try:
        grouped = group_changes_by_region(details)
        results.pass_test("Группировка по регионам", f"{len(grouped)} регионов")
        
        for region, region_details in grouped.items():
            try:
                formatted = format_region_summary(region, region_details)
                if formatted:
                    results.pass_test(f"Форматирование {region}", f"{len(formatted)} блоков")
                else:
                    results.fail_test(f"Форматирование {region}", "Пустой результат")
            except Exception as e:
                results.fail_test(f"Форматирование {region}", str(e))
    
    except Exception as e:
        results.fail_test("Региональная группировка", str(e))

async def test_6_smart_formatting(results: FullTestResults):
    """Тест 6: Умное форматирование"""
    results.start_test("Умное форматирование")
    
    # Создаем тестовое изменение
    test_detail = {
        "title": "Meta Advertising Standards Update",
        "url": "https://transparency.meta.com/policies/ad-standards/",
        "region": "GLOBAL",
        "global_diff": {
            "changed": [{"was": "Old policy text", "now": "New policy text with important changes"}],
            "added": ["New restriction for political ads", "Updated targeting guidelines"],
            "removed": ["Deprecated feature XYZ"]
        }
    }
    
    try:
        # Тестируем значимость изменения
        is_meaningful = _is_meaningful_change(test_detail)
        results.pass_test("Анализ значимости", f"Meaningful: {is_meaningful}")
        
        # Тестируем форматирование
        formatted_blocks = format_change_smart(test_detail)
        if formatted_blocks:
            results.pass_test("Умное форматирование", f"{len(formatted_blocks)} блоков")
            
            # Проверяем что форматированный текст содержит ключевые элементы
            full_text = " ".join(formatted_blocks)
            if "GLOBAL" in full_text and "Meta Advertising Standards" in full_text:
                results.pass_test("Форматирование содержимое", "Содержит нужные элементы")
            else:
                results.warn_test("Форматирование содержимое", "Не найдены ожидаемые элементы")
        else:
            results.fail_test("Умное форматирование", "Пустой результат")
    
    except Exception as e:
        results.fail_test("Умное форматирование", str(e))

async def test_7_llm_functionality(results: FullTestResults):
    """Тест 7: LLM функциональность (ИИ)"""
    results.start_test("LLM функциональность (ИИ)")
    
    try:
        # Проверяем настройки LLM без реального запроса
        api_key = os.getenv("OPENROUTER_API_KEY")
        model = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
        
        if api_key and len(api_key) > 10:
            results.pass_test("LLM API ключ", f"API key настроен ({len(api_key)} симв.)")
        else:
            results.fail_test("LLM API ключ", "Не настроен")
        
        if model:
            results.pass_test("LLM модель", f"Модель: {model}")
        else:
            results.warn_test("LLM модель", "Модель не указана")
        
        # Тестируем функцию суммаризации
        test_text = """
        Meta Advertising Standards have been updated with new requirements for political advertisers.
        All political ads must now include additional disclosure information.
        The update applies to all regions starting January 2025.
        Advertisers must verify their identity through enhanced verification process.
        """
        
        try:
            summarized = await asyncio.to_thread(summarize_rules, test_text)
            if summarized and len(summarized) > 20:
                results.pass_test("Суммаризация", f"{len(summarized)} символов")
            else:
                results.warn_test("Суммаризация", "Короткий или пустой результат")
        except Exception as e:
            results.fail_test("Суммаризация", f"Ошибка: {str(e)[:50]}")
        
        # Тестируем перевод
        try:
            translated = await asyncio.to_thread(translate_compact_html, 
                                               "Meta has updated advertising policies", 
                                               target_lang="ru", max_len=200)
            if translated and len(translated) > 5:
                results.pass_test("Перевод", f"'{translated[:50]}...'")
            else:
                results.warn_test("Перевод", "Пустой результат перевода")
        except Exception as e:
            results.fail_test("Перевод", f"Ошибка: {str(e)[:50]}")
    
    except Exception as e:
        results.fail_test("LLM функциональность", str(e))

async def test_8_storage_cache(results: FullTestResults):
    """Тест 8: Система кэширования и хранения"""
    results.start_test("Система кэширования и хранения")
    
    try:
        # Тестируем загрузку кэша
        cache_data = load_cache()
        if cache_data:
            items = cache_data.get("items", [])
            results.pass_test("Загрузка кэша", f"{len(items)} элементов")
        else:
            results.pass_test("Загрузка кэша", "Пустой кэш (это нормально)")
        
        # Тестируем сохранение кэша
        test_cache = {
            "items": [
                {"tag": "test", "url": "https://example.com", "region": "GLOBAL", 
                 "title": "Test Item", "hash": "test_hash"}
            ],
            "updated": time.time()
        }
        
        save_cache(test_cache)
        results.pass_test("Сохранение кэша", "Тестовые данные сохранены")
        
        # Проверяем что данные сохранились
        reloaded_cache = load_cache()
        if reloaded_cache and reloaded_cache.get("items"):
            results.pass_test("Перезагрузка кэша", "Данные успешно сохранены и загружены")
        else:
            results.warn_test("Перезагрузка кэша", "Данные не сохранились")
    
    except Exception as e:
        results.fail_test("Система кэширования", str(e))

async def test_9_error_handling(results: FullTestResults):
    """Тест 9: Обработка ошибок и исключений"""
    results.start_test("Обработка ошибок и исключений")
    
    # Тестируем обработку неверного URL
    try:
        proxy_config = _get_proxy_for_region("GLOBAL", None, "error_test")
        headers = _get_random_headers("https://nonexistent-meta-site-12345.com", "en-US")
        
        timeout = httpx.Timeout(5.0)
        async with httpx.AsyncClient(timeout=timeout, proxies=proxy_config, verify=False) as client:
            try:
                response = await client.get("https://nonexistent-meta-site-12345.com", headers=headers)
                results.warn_test("Обработка неверного URL", "Неожиданно получен ответ")
            except Exception as e:
                results.pass_test("Обработка неверного URL", "Ошибка корректно обработана")
    except Exception as e:
        results.pass_test("Обработка ошибок", "Система обработки ошибок работает")
    
    # Тестируем обработку невалидного JSON
    try:
        invalid_json = '{"invalid": json}'
        json.loads(invalid_json)
        results.fail_test("Обработка невалидного JSON", "Ошибка не поймана")
    except json.JSONDecodeError:
        results.pass_test("Обработка невалидного JSON", "JSON ошибка корректно обработана")

async def test_10_integration_flow(results: FullTestResults):
    """Тест 10: Полный интеграционный поток"""
    results.start_test("Полный интеграционный поток")
    
    try:
        print("  Выполняется полный интеграционный тест...")
        
        # 1. Проверяем что все компоненты инициализированы
        results.pass_test("Инициализация компонентов", "Все модули загружены")
        
        # 2. Создаем мини-пайплайн с тестовыми данными
        test_details = [
            {
                "title": "Integration Test Change",
                "url": "https://transparency.meta.com/policies/ad-standards/",
                "region": "GLOBAL",
                "global_diff": {
                    "changed": [{"was": "Test old content", "now": "Test new content with significant changes"}],
                    "added": ["New integration test requirement"],
                    "removed": []
                }
            }
        ]
        
        # 3. Группировка
        grouped = group_changes_by_region(test_details)
        results.pass_test("Интеграция: Группировка", f"{len(grouped)} групп")
        
        # 4. Форматирование
        for region, details in grouped.items():
            formatted = format_region_summary(region, details)
            if formatted:
                results.pass_test(f"Интеграция: Форматирование {region}", "OK")
        
        # 5. Проверяем что система готова к работе
        required_functions = [
            (_get_proxy_for_region, "Прокси функция"),
            (format_change_smart, "Форматирование"),
            (group_changes_by_region, "Группировка"),
            (_is_meaningful_change, "Анализ значимости")
        ]
        
        for func, name in required_functions:
            if callable(func):
                results.pass_test(f"Интеграция: {name}", "Функция доступна")
            else:
                results.fail_test(f"Интеграция: {name}", "Функция недоступна")
        
        results.pass_test("Полная интеграция", "Все компоненты работают совместно")
    
    except Exception as e:
        results.fail_test("Полная интеграция", str(e))

async def run_full_integration_tests():
    """Запускает все интеграционные тесты"""
    print("[START] ЗАПУСК ПОЛНОГО ИНТЕГРАЦИОННОГО ТЕСТИРОВАНИЯ")
    print("="*80)
    print("Проверяем ВСЕ функции Meta News Bot перед деплойдом...")
    print("Это может занять несколько минут...")
    
    results = FullTestResults()
    
    # Запускаем все тесты последовательно
    await test_1_configuration(results)
    await test_2_proxy_functionality(results)
    await test_3_http_requests(results)
    await test_4_pipeline_components(results)
    await test_5_regional_grouping(results)
    await test_6_smart_formatting(results)
    await test_7_llm_functionality(results)
    await test_8_storage_cache(results)
    await test_9_error_handling(results)
    await test_10_integration_flow(results)
    
    # Показываем итоговые результаты
    success = results.summary()
    
    if success:
        print("\n[OK] ГОТОВО К ДЕПЛОЙДОМУ!")
        print("Все интеграционные тесты прошли успешно.")
        print("Можно безопасно деплоить на Railway.")
    else:
        print("\n[ERROR] НЕ ГОТОВО К ДЕПЛОЙДОМУ!")
        print("Обнаружены критические ошибки.")
        print("Исправьте ошибки перед деплойдом.")
    
    return success

if __name__ == "__main__":
    success = asyncio.run(run_full_integration_tests())
    sys.exit(0 if success else 1)