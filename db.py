import sqlite3
import os
import time
from typing import Any

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "radio_history.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listening_history (
                url TEXT PRIMARY KEY,
                stationuuid TEXT,
                name TEXT,
                last_listened_at REAL DEFAULT 0,
                listen_duration REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorite_stations (
                url TEXT PRIMARY KEY,
                stationuuid TEXT,
                name TEXT,
                added_at REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS station_metadata_cache (
                stationuuid TEXT PRIMARY KEY,
                name TEXT,
                url TEXT,
                url_resolved TEXT,
                tags_raw TEXT,
                fetched_at REAL DEFAULT 0
            )
        """)

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listening_history_duration "
            "ON listening_history(listen_duration DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_listening_history_stationuuid "
            "ON listening_history(stationuuid)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_favorite_stations_stationuuid "
            "ON favorite_stations(stationuuid)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_station_metadata_cache_url "
            "ON station_metadata_cache(url)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_station_metadata_cache_url_resolved "
            "ON station_metadata_cache(url_resolved)"
        )
        conn.commit()


def cache_stations(stations: list[dict[str, Any]]):
    now = time.time()
    rows = []
    for station in stations:
        stationuuid = station.get("stationuuid")
        if not stationuuid:
            continue
        rows.append(
            (
                stationuuid,
                station.get("name", ""),
                station.get("url", ""),
                station.get("url_resolved", ""),
                station.get("tags", ""),
                now,
            )
        )

    if not rows:
        return

    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO station_metadata_cache (stationuuid, name, url, url_resolved, tags_raw, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(stationuuid) DO UPDATE SET
                name = excluded.name,
                url = excluded.url,
                url_resolved = excluded.url_resolved,
                tags_raw = excluded.tags_raw,
                fetched_at = excluded.fetched_at
            """,
            rows,
        )
        conn.commit()

def add_favorite(url: str, name: str = "", stationuuid: str = ""):
    now = time.time()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO favorite_stations (url, stationuuid, name, added_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                stationuuid = CASE
                    WHEN ? != '' THEN ?
                    ELSE favorite_stations.stationuuid
                END,
                name = CASE
                    WHEN ? != '' THEN ?
                    ELSE favorite_stations.name
                END
        """, (url, stationuuid, name, now, stationuuid, stationuuid, name, name))
        conn.commit()

def remove_favorite(url: str):
    with get_db() as conn:
        conn.execute("""
            DELETE FROM favorite_stations WHERE url = ?
        """, (url,))
        conn.commit()

def get_favorites():
    with get_db() as conn:
        cur = conn.execute("""
            SELECT
                f.url,
                COALESCE(NULLIF(f.stationuuid, ''), h.stationuuid, '') AS stationuuid,
                COALESCE(NULLIF(f.name, ''), h.name, '') AS name,
                COALESCE(h.last_listened_at, 0) AS last_listened_at,
                COALESCE(h.listen_duration, 0) AS listen_duration
            FROM favorite_stations f
            LEFT JOIN listening_history h ON h.url = f.url
            ORDER BY name ASC
        """)
        return [dict(row) for row in cur.fetchall()]

def update_listening_history(
    url: str, duration: float, name: str = "", stationuuid: str = ""
):
    now = time.time()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO listening_history (url, stationuuid, name, last_listened_at, listen_duration)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                stationuuid = CASE
                    WHEN ? != '' THEN ?
                    ELSE listening_history.stationuuid
                END,
                last_listened_at = ?,
                listen_duration = listen_duration + ?,
                name = CASE WHEN ? != '' THEN ? ELSE name END
        """, (
            url,
            stationuuid,
            name,
            now,
            duration,
            stationuuid,
            stationuuid,
            now,
            duration,
            name,
            name,
        ))
        conn.commit()

def get_my_recent_stations(limit: int = 10):
    with get_db() as conn:
        cur = conn.execute("SELECT url, stationuuid, name, last_listened_at, listen_duration FROM listening_history WHERE last_listened_at > 0 ORDER BY last_listened_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]

def get_my_top_stations(limit: int = 10):
    with get_db() as conn:
        cur = conn.execute("SELECT url, stationuuid, name, last_listened_at, listen_duration FROM listening_history WHERE listen_duration > 0 ORDER BY listen_duration DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]


def get_listened_stations_with_tags():
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT
                s.url,
                s.stationuuid,
                s.name,
                s.listen_duration,
                COALESCE(c0.tags_raw, c1.tags_raw, c2.tags_raw, '') AS tags_raw
            FROM listening_history s
            LEFT JOIN station_metadata_cache c0 ON c0.stationuuid = s.stationuuid
            LEFT JOIN station_metadata_cache c1 ON c1.url = s.url
            LEFT JOIN station_metadata_cache c2 ON c2.url_resolved = s.url
            WHERE s.listen_duration > 0
            ORDER BY s.listen_duration DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def find_stationuuid_by_url(url: str) -> str:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT stationuuid
            FROM station_metadata_cache
            WHERE url = ? OR url_resolved = ?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (url, url),
        ).fetchone()
        if not row:
            return ""
        return row["stationuuid"] or ""
