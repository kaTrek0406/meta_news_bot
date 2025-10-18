#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Безопасный деплойд с полным интеграционным тестированием
Использование: python safe_deploy.py "commit message"
"""

import sys
import subprocess
import os

def run_command(cmd, check=True):
    """Выполняет команду и возвращает результат"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd())
        if check and result.returncode != 0:
            print(f"[-] Ошибка выполнения команды: {cmd}")
            print(f"Stderr: {result.stderr}")
            return False
        return result
    except Exception as e:
        print(f"[-] Исключение при выполнении {cmd}: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Использование: python safe_deploy.py \"commit message\"")
        print("Пример: python safe_deploy.py \"feat: add new functionality\"")
        sys.exit(1)
    
    commit_message = " ".join(sys.argv[1:])
    
    print("[DEPLOY] БЕЗОПАСНЫЙ ДЕПЛОЙД С ПОЛНЫМ ТЕСТИРОВАНИЕМ")
    print("=" * 60)
    print(f"[MSG] Сообщение коммита: {commit_message}")
    print()
    
    # Шаг 1: Запускаем полное интеграционное тестирование
    print("[1] Шаг 1: Полное интеграционное тестирование...")
    print("     Это займет несколько минут - тестируем ВСЕ функции...")
    
    test_result = run_command("python test_full_integration.py")
    if not test_result or test_result.returncode != 0:
        print("[-] Интеграционные тесты провалились! Деплойд отменен.")
        print("Исправьте ошибки и попробуйте снова.")
        print()
        print("[INFO] Если хотите быстрые тесты, используйте: python safe_commit.py")
        sys.exit(1)
    
    print("[+] Все интеграционные тесты прошли успешно!")
    print()
    
    # Шаг 2: Запускаем быстрые unit-тесты для дополнительной проверки
    print("[2] Шаг 2: Дополнительные unit-тесты...")
    unit_test_result = run_command("python run_tests.py")
    if not unit_test_result or unit_test_result.returncode != 0:
        print("[-] Unit-тесты провалились! Деплойд отменен.")
        sys.exit(1)
    
    print("[+] Unit-тесты также прошли успешно!")
    print()
    
    # Шаг 3: Добавляем все изменения
    print("[3] Шаг 3: Добавление изменений в git...")
    if not run_command("git add ."):
        print("[-] Ошибка git add")
        sys.exit(1)
    
    # Шаг 4: Показываем что будет закоммичено
    print("[FILES] Изменения для коммита:")
    status_result = run_command("git status --porcelain", check=False)
    if status_result:
        print(status_result.stdout)
    
    # Шаг 5: Коммитим
    print(f"[4] Шаг 4: Создание коммита...")
    commit_cmd = f'git commit -m "{commit_message}"'
    if not run_command(commit_cmd):
        print("[-] Ошибка git commit")
        sys.exit(1)
    
    # Шаг 6: Отправляем на GitHub
    print("[5] Шаг 5: Отправка на GitHub...")
    if not run_command("git push origin main"):
        print("[-] Ошибка git push")
        print("Коммит создан локально, но не отправлен на GitHub")
        sys.exit(1)
    
    print()
    print("[OK] УСПЕШНЫЙ ДЕПЛОЙД!")
    print("[+] Полные интеграционные тесты прошли")
    print("[+] Unit-тесты прошли")
    print("[+] Коммит создан")
    print("[+] Changes pushed to GitHub")
    print()
    print("🚀 БОТ ГОТОВ К РАБОТЕ НА RAILWAY!")
    print("   Все функции протестированы и работают корректно.")
    print("   Railway автоматически подхватит обновление.")

if __name__ == "__main__":
    main()