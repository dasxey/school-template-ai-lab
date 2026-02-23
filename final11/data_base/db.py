from datetime import datetime
import sqlite3
from pathlib import Path
from typing import List, Dict


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mindheaven.db"


def init_db() -> None:
    """Ініціалізація простої SQLite-бази для щоденника емоцій."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                text TEXT NOT NULL,
                mood TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def add_entry(text: str, mood: str) -> None:
    """Додає один запис до таблиці entries."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO entries (created_at, text, mood) VALUES (?, ?, ?)",
            (datetime.utcnow().isoformat(), text, mood),
        )
        conn.commit()
    finally:
        conn.close()


def get_entries(limit: int = 10) -> List[Dict[str, str]]:
    """Повертає останні N записів щоденника емоцій у вигляді списку словників."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT created_at, text, mood FROM entries "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    history = [
        {"created_at": r[0], "text": r[1], "mood": r[2]}
        for r in rows
    ]
    # Повертаємо в зворотному порядку, щоб на графіку було від старіших до новіших
    history.reverse()
    return history


