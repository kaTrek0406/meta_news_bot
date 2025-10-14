import urllib.request
import ssl

# Прокси с явной привязкой к Молдове
proxy = 'http://brd-customer-hl_3967120c-zone-residential_proxy1-country-md:viv0l29v3tb2@brd.superproxy.io:33335'
url = 'https://geo.brdtest.com/mygeo.json'

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({'https': proxy, 'http': proxy}),
    urllib.request.HTTPSHandler(context=ssl._create_unverified_context())
)

print("🔍 Тестирование прокси с привязкой к Молдове...")
print(f"Прокси: {proxy.split('@')[1]}")
print(f"URL: {url}\n")

try:
    response = opener.open(url, timeout=30).read().decode()
    print("✅ Успешно подключились через прокси!")
    print("\n📍 Информация о подключении:")
    print(response)
except Exception as e:
    print(f"❌ Ошибка: {e}")
    print("\n💡 Возможные причины:")
    print("1. Нет доступных IP в Молдове (no_peer)")
    print("2. Неправильные credentials")
    print("3. Таймаут подключения")
