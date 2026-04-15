"""
Точка входу для запуску MindHeaven.

1. Піднімає FastAPI-бекенд з файлу backend/app.py.
2. Відкриває сайт у браузері за адресою http://127.0.0.1:8000/
"""

import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from dotenv import load_dotenv
load_dotenv()

import uvicorn

# Імпортуємо app з правильного місця (якщо в backend/app.py є app = FastAPI())
from backend.app import app

HOST = "127.0.0.1"
PORT = int(os.environ.get("MINDHEAVEN_PORT", "8000"))


def _port_available(host: str, port: int) -> bool:
    """True, якщо можна зайняти порт (нічого іншого на ньому не слухає)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def run_server() -> None:
    """Запуск uvicorn-сервера без reload (щоб уникнути проблем у потоках)."""
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",  # показує тільки важливе
        reload=False,  # без reload — стабільніше
        workers=1,  # один воркер — простіше для Mac
    )


def _health_ok(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/health", timeout=3) as r:
            body = r.read().decode("utf-8", errors="ignore")
            return r.status == 200 and "MindHeaven" in body
    except (OSError, urllib.error.URLError, ValueError):
        return False


def main() -> None:
    print("Запускаємо MindHeaven...")

    if not _port_available(HOST, PORT):
        print(
            f"\n❌ Порт {PORT} зайнятий (address already in use).\n"
            "Закрий інший термінал з uvicorn/python або зупини старий процес:\n"
            f"   lsof -i TCP:{PORT} -sTCP:LISTEN\n"
            "   kill <PID>\n"
            "Або інший порт: MINDHEAVEN_PORT=8001 (сторінки відкривай з того ж хоста/порта — API сам підхопить origin).\n"
            "Найпростіше — звільнити поточний порт.\n"
        )
        raise SystemExit(1)

    base_url = f"http://{HOST}:{PORT}"
    # 1. Запускаємо сервер у фоновому потоці
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # 2. Даємо серверу час піднятись і перевіряємо /health
    for _ in range(30):
        time.sleep(0.2)
        if _health_ok(base_url):
            break
    else:
        print(
            f"\n⚠️ Сервер не відповів на {base_url}/health за очікуваний час.\n"
            "Переглянь лог uvicorn вище — можлива помилка запуску.\n"
        )

    # 3. Відкриваємо сайт через HTTP (не file://), щоб запити до API працювали стабільно
    url = f"{base_url}/"

    try:
        webbrowser.open_new_tab(url)
        print(f"Браузер відкрито: {url}")
    except Exception as e:
        print(f"Не вдалося автоматично відкрити браузер: {e}")
        print(f"Відкрий вручну: {url}")

    print("\nMindHeaven запущено!")
    print(f"Сервер: {base_url}")
    print(f"Інтерфейс: {url} (відкрий у браузері, якщо не відкрився сам)")
    print("Щоб зупинити — натисни Ctrl+C в терміналі\n")

    # 4. Тримаємо програму живою, поки не натиснеш Ctrl+C
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nЗупиняємо MindHeaven...")


if __name__ == "__main__":
    main()