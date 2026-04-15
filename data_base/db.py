from datetime import datetime
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Any


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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                summary TEXT NOT NULL,
                polarity TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                quote TEXT
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
        {
            "created_at": r[0],
            "timestamp": r[0],
            "text": r[1],
            "mood": r[2],
        }
        for r in rows
    ]
    # Повертаємо в зворотному порядку, щоб на графіку було від старіших до новіших
    history.reverse()
    return history


def add_insight(
    summary: str,
    polarity: str,
    importance: int,
    quote: Optional[str] = None,
) -> None:
    """Додає короткий інсайт (що хвилювало / тішило / важливо з погляду помічника)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO insights (created_at, summary, polarity, importance, quote) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.utcnow().isoformat(),
                summary.strip(),
                polarity.strip().lower(),
                max(1, min(5, importance)),
                (quote or "").strip() or None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_insights(limit: int = 100) -> List[Dict[str, Any]]:
    """Останні інсайти для сторінки щоденника (важливе з роком/місцем у пам'яті)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT created_at, summary, polarity, importance, quote "
            "FROM insights ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "created_at": r[0],
            "timestamp": r[0],
            "summary": r[1],
            "polarity": r[2],
            "importance": r[3],
            "quote": r[4] or "",
        }
        for r in rows
    ]


