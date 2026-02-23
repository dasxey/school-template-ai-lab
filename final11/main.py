"""
Точка входу для запуску MindHeaven.

1. Піднімає FastAPI-бекенд з файлу backend/app.py.
2. Автоматично відкриває інтерфейс visual/index.html у браузері.
"""

import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


def _run_server() -> None:
    """Запуск uvicorn-сервера в окремому потоці без режиму reload."""
    uvicorn.run(
        "backend.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


def main() -> None:
    # 1. Запускаємо сервер у фоновому потоці
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # 2. Даємо серверу кілька секунд, щоб піднятися
    time.sleep(2)

    # 3. Відкриваємо інтерфейс у браузері
    index_path = Path(__file__).parent / "visual" / "index.html"
    try:
        webbrowser.open_new_tab(index_path.as_uri())
    except Exception:
        # Якщо щось пішло не так, просто виведемо шлях у консоль
        print(f"Відкрий вручну файл інтерфейсу: {index_path}")

    print("MindHeaven запущено. Сервер: http://127.0.0.1:8000")

    # 4. Чекаємо, поки процес не буде перервано (Ctrl+C)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Зупинка MindHeaven...")


if __name__ == "__main__":
    main()


