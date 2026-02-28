import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "radio_history.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stations (
                url TEXT PRIMARY KEY,
                name TEXT,
                is_favorite INTEGER DEFAULT 0,
                last_listened_at REAL DEFAULT 0,
                listen_duration REAL DEFAULT 0
            )
        """)
        conn.commit()

def add_favorite(url: str, name: str = ""):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO stations (url, name, is_favorite)
            VALUES (?, ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                is_favorite = 1,
                name = CASE WHEN ? != '' THEN ? ELSE name END
        """, (url, name, name, name))
        conn.commit()

def remove_favorite(url: str):
    with get_db() as conn:
        conn.execute("""
            UPDATE stations SET is_favorite = 0 WHERE url = ?
        """, (url,))
        conn.commit()

def get_favorites():
    with get_db() as conn:
        cur = conn.execute("SELECT url, name, last_listened_at, listen_duration FROM stations WHERE is_favorite = 1 ORDER BY name ASC")
        return [dict(row) for row in cur.fetchall()]

def update_listening_history(url: str, duration: float, name: str = ""):
    now = time.time()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO stations (url, name, last_listened_at, listen_duration)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                last_listened_at = ?,
                listen_duration = listen_duration + ?,
                name = CASE WHEN ? != '' THEN ? ELSE name END
        """, (url, name, now, duration, now, duration, name, name))
        conn.commit()

def get_my_recent_stations(limit: int = 10):
    with get_db() as conn:
        cur = conn.execute("SELECT url, name, last_listened_at, listen_duration FROM stations WHERE last_listened_at > 0 ORDER BY last_listened_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]

def get_my_top_stations(limit: int = 10):
    with get_db() as conn:
        cur = conn.execute("SELECT url, name, last_listened_at, listen_duration FROM stations WHERE listen_duration > 0 ORDER BY listen_duration DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]
