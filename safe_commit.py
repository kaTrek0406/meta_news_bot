#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Безопасный коммит с предварительным тестированием
Использование: python safe_commit.py "commit message"
"""

import sys
import subprocess
import os

def run_command(cmd, check=True):
    """Выполняет команду и возвращает результат"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd())
        if check and result.returncode != 0:
            print(f"❌ Ошибка выполнения команды: {cmd}")
            print(f"Stderr: {result.stderr}")
            return False
        return result
    except Exception as e:
        print(f"❌ Исключение при выполнении {cmd}: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Использование: python safe_commit.py \"commit message\"")
        print("Пример: python safe_commit.py \"fix: improve error handling\"")
        sys.exit(1)
    
    commit_message = " ".join(sys.argv[1:])
    
    print("[COMMIT] БЕЗОПАСНЫЙ КОММИТ С ТЕСТИРОВАНИЕМ")
    print("=" * 50)
    print(f"[MSG] Сообщение коммита: {commit_message}")
    print()
    
    # Шаг 1: Запускаем все тесты
    print("[1] Шаг 1: Запуск тестов...")
    test_result = run_command("python run_tests.py")
    if not test_result or test_result.returncode != 0:
        print("[-] Тесты провалились! Коммит отменен.")
        print("Исправьте ошибки и попробуйте снова.")
        sys.exit(1)
    
    print("[+] Все тесты прошли успешно!")
    print()
    
    # Шаг 2: Добавляем все изменения
    print("[2] Шаг 2: Добавление изменений в git...")
    if not run_command("git add ."):
        print("[-] Ошибка git add")
        sys.exit(1)
    
    # Шаг 3: Показываем что будет закоммичено
    print("[FILES] Изменения для коммита:")
    status_result = run_command("git status --porcelain", check=False)
    if status_result:
        print(status_result.stdout)
    
    # Шаг 4: Коммитим
    print(f"[3] Шаг 3: Создание коммита...")
    commit_cmd = f'git commit -m "{commit_message}"'
    if not run_command(commit_cmd):
        print("[-] Ошибка git commit")
        sys.exit(1)
    
    # Шаг 5: Отправляем на GitHub
    print("[4] Шаг 4: Отправка на GitHub...")
    if not run_command("git push origin main"):
        print("[-] Ошибка git push")
        print("Коммит создан локально, но не отправлен на GitHub")
        sys.exit(1)
    
    print()
    print("[OK] УСПЕШНО!")
    print("[+] Тесты прошли")
    print("[+] Коммит создан")
    print("[+] Changes pushed to GitHub")
    print()
    print("Ваши изменения безопасно отправлены в репозиторий!")

if __name__ == "__main__":
    main()