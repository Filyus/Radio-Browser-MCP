# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp",
#     "requests>=2.28.0",
#     "python-vlc",
# ]
# ///

import os
import sys
import threading
import time
import urllib.parse
import atexit
from typing import Any

import requests
import vlc
from mcp.server.fastmcp import FastMCP
import db
import app

# Initialize database
db.init_db()

# Initialize MCP server
mcp = FastMCP("radio-browser-mcp")

# Global VLC instance and player
vlc_instance = None
player = None
vlc_init_error = None
try:
    vlc_instance = vlc.Instance("--no-video")
    player = vlc_instance.media_player_new()
except Exception as e:
    vlc_init_error = str(e)

is_intentionally_stopped = False
current_radio_url = None

# Database tracking state
current_db_url = None
current_db_name = None
current_db_stationuuid = None
playback_start_time = None
last_db_update_time = None
tracking_timer = None
tracking_timer_lock = threading.Lock()

# Tracking configuration
ENABLE_BACKGROUND_TRACKING = os.environ.get(
    "RADIO_ENABLE_BACKGROUND_TRACKING", "true"
).lower() in ("true", "1", "yes")

TRACKING_INTERVAL = float(
    os.environ.get("RADIO_TRACKING_INTERVAL", 60.0)
)
MAX_PLAYLIST_BYTES = int(os.environ.get("RADIO_MAX_PLAYLIST_BYTES", 262144))


def _ensure_player_ready() -> str | None:
    if player is None or vlc_instance is None:
        return (
            "VLC is not available. Install VLC/libVLC and ensure python-vlc can "
            f"initialize it. Details: {vlc_init_error or 'unknown error'}"
        )
    return None

def _update_duration():
    global current_db_url, current_db_name, current_db_stationuuid
    global last_db_update_time, tracking_timer

    with tracking_timer_lock:
        if not current_db_url or not last_db_update_time:
            return

        now = time.time()
        duration = now - last_db_update_time
        if duration > 0:
            try:
                db.update_listening_history(
                    current_db_url,
                    duration,
                    current_db_name,
                    current_db_stationuuid or "",
                )
                last_db_update_time = now
            except Exception as e:
                print(f"Error updating duration: {e}", file=sys.stderr)

        # Schedule next update
        if ENABLE_BACKGROUND_TRACKING:
            tracking_timer = threading.Timer(TRACKING_INTERVAL, _update_duration)
            tracking_timer.daemon = True
            tracking_timer.start()

def _track_final_duration():
    _update_duration()
    with tracking_timer_lock:
        global tracking_timer
        if tracking_timer:
            tracking_timer.cancel()
            tracking_timer = None

atexit.register(_track_final_duration)

# Reconnection configuration (normalized as constants)
INITIAL_RECONNECT_DELAY = float(
    os.environ.get("RADIO_INITIAL_RECONNECT_DELAY", 0.1)
)
MAX_RECONNECT_DELAY = float(
    os.environ.get("RADIO_MAX_RECONNECT_DELAY", 30.0)
)
RECONNECT_BACKOFF_THRESHOLD = float(
    os.environ.get("RADIO_RECONNECT_BACKOFF_THRESHOLD", 5.0)
)

# Reconnection state
current_reconnect_delay = INITIAL_RECONNECT_DELAY
last_reconnect_attempt_time = 0
reconnect_timer: threading.Timer | None = None
reconnect_timer_lock = threading.Lock()
player_event_handlers_attached = False


def get_playstate_str(state):
    # Map vlc.State enum to string representation
    states = {
        vlc.State.NothingSpecial: "Stopped",
        vlc.State.Opening: "Opening",
        vlc.State.Buffering: "Buffering",
        vlc.State.Playing: "Playing",
        vlc.State.Paused: "Paused",
        vlc.State.Stopped: "Stopped",
        vlc.State.Ended: "Ended",
        vlc.State.Error: "Error",
    }
    return states.get(state, f"Unknown ({state})")


def _cache_stations_result(stations: Any) -> None:
    if not isinstance(stations, list):
        return
    try:
        db.cache_stations(stations)
    except Exception as e:
        print(f"Warning: Failed to cache stations metadata: {e}", file=sys.stderr)


def _parse_tags(tags_raw: str) -> list[str]:
    if not isinstance(tags_raw, str) or not tags_raw.strip():
        return []

    parsed: list[str] = []
    seen: set[str] = set()
    for part in tags_raw.split(","):
        tag = part.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        parsed.append(tag)
    return parsed


@mcp.tool()
def get_radio_stats() -> dict:
    """
    Get Radio Browser statistics (stations, countries, and other metrics).

    Returns:
        dict: Statistics about the Radio Browser database
    """
    try:
        result = app.get_radiobrowser_stats()
        return {"success": True, "stats": result}
    except Exception as e:
        return {"success": False, "stats": {}, "error": str(e)}


@mcp.tool()
def get_available_servers() -> dict[str, Any]:
    """
    Get list of all available Radio Browser API servers.

    Returns:
        dict[str, Any]: Success flag and list of Radio Browser server URLs
    """
    try:
        servers = app.get_radiobrowser_base_urls()
        return {"success": True, "servers": servers}
    except Exception as e:
        return {"success": False, "servers": [], "error": str(e)}


@mcp.tool()
def search_stations_by_country_code(country_code: str) -> dict[str, Any]:
    """
    Search radio stations by country code.

    Args:
        country_code (str): Two-letter country code (e.g., 'US', 'DE', 'TR', 'GB', 'FR')

    Returns:
        dict[str, Any]: Success flag and list of matching radio stations
    """
    try:
        result = app.search_stations_by_country(country_code.upper())
        _cache_stations_result(result)
        return {"success": True, "stations": result}
    except Exception as e:
        return {"success": False, "stations": [], "error": str(e)}


@mcp.tool()
def search_stations_by_station_name(name: str) -> dict[str, Any]:
    """
    Search radio stations by name or partial name.

    Args:
        name (str): Name or partial name of the radio station to search for

    Returns:
        dict[str, Any]: Success flag and list of matching radio stations
    """
    try:
        result = app.search_stations_by_name(name)
        _cache_stations_result(result)
        return {"success": True, "stations": result}
    except Exception as e:
        return {"success": False, "stations": [], "error": str(e)}


@mcp.tool()
def search_stations_by_tag(tag: str) -> dict[str, Any]:
    """
    Search radio stations by tag (genre).

    Args:
        tag (str): Tag or genre to search for (e.g., 'jazz', 'rock', 'classical')

    Returns:
        dict[str, Any]: Success flag and list of matching radio stations
    """
    try:
        result = app.search_stations_by_tag(tag)
        _cache_stations_result(result)
        return {"success": True, "stations": result}
    except Exception as e:
        return {"success": False, "stations": [], "error": str(e)}


@mcp.tool()
def search_global_top_voted_stations(limit: int = 10) -> dict[str, Any]:
    """
    Get the top voted stations globally from the Radio Browser database.

    Args:
        limit (int): Number of stations to return (default 10)

    Returns:
        dict[str, Any]: Success flag and list of top voted radio stations
    """
    try:
        result = app.get_top_voted_stations(limit)
        _cache_stations_result(result)
        return {"success": True, "stations": result}
    except Exception as e:
        return {"success": False, "stations": [], "error": str(e)}


@mcp.tool()
def search_global_top_clicked_stations(limit: int = 10) -> dict[str, Any]:
    """
    Get the most clicked stations globally from the Radio Browser database.

    Args:
        limit (int): Number of stations to return (default 10)

    Returns:
        dict[str, Any]: Success flag and list of most clicked radio stations
    """
    try:
        result = app.get_top_clicked_stations(limit)
        _cache_stations_result(result)
        return {"success": True, "stations": result}
    except Exception as e:
        return {"success": False, "stations": [], "error": str(e)}


@mcp.tool()
def get_available_tags(limit: int = 100, order: str = "stationcount") -> dict[str, Any]:
    """
    Get available tags from the Radio Browser database.

    Args:
        limit (int): Number of tags to return (default 100, max 1000)
        order (str): Sort order, one of "stationcount" or "name"

    Returns:
        dict[str, Any]: Success flag and list of tags
    """
    try:
        normalized_order = (order or "stationcount").strip().lower()
        if normalized_order not in {"stationcount", "name"}:
            normalized_order = "stationcount"

        safe_limit = max(1, min(1000, int(limit)))
        result = app.get_available_tags(limit=safe_limit, order=normalized_order)
        return {"success": True, "tags": result}
    except Exception as e:
        return {"success": False, "tags": [], "error": str(e)}


def _extract_stream_url_from_playlist(url: str, content: str) -> str | None:
    lines = content.splitlines()
    lower_url = url.lower()

    if lower_url.endswith(".pls"):
        for line in lines:
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.lower().startswith("file") and value.strip():
                candidate = value.strip()
                if candidate.startswith(("http://", "https://")):
                    return candidate
                return urllib.parse.urljoin(url, candidate)
        return None

    # .m3u parser: first non-comment/non-empty entry is stream URI.
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")):
            return line
        return urllib.parse.urljoin(url, line)
    return None


def resolve_stream_url(url: str) -> str:
    """Attempts to resolve .m3u/.pls playlists to their stream URL."""
    try:
        # Check if it's a known playlist format or if we should peek.
        # Do not parse .m3u8 (HLS) manually; VLC handles adaptive playlists.
        if url.lower().endswith(".m3u") or url.lower().endswith(".pls"):
            response = requests.get(
                url,
                headers={"User-Agent": app.USER_AGENT},
                timeout=5.0,
                stream=True,
            )
            response.raise_for_status()
            chunks = []
            read_total = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                read_total += len(chunk)
                if read_total > MAX_PLAYLIST_BYTES:
                    break
                chunks.append(chunk)

            content = b"".join(chunks).decode("utf-8", errors="ignore")
            resolved = _extract_stream_url_from_playlist(url, content)
            if resolved:
                return resolved
        return url
    except Exception as e:
        print(f"Warning: Failed to resolve playlist URL {url}: {e}")
        return url


current_track_name = None


def reconnect_callback(event, player_instance):
    global is_intentionally_stopped, current_radio_url
    global current_reconnect_delay, last_reconnect_attempt_time, reconnect_timer

    if is_intentionally_stopped or not current_radio_url:
        return

    now = time.time()

    # If we are reconnecting too soon, increase backoff
    if now - last_reconnect_attempt_time < RECONNECT_BACKOFF_THRESHOLD:
        current_reconnect_delay = min(current_reconnect_delay * 2, MAX_RECONNECT_DELAY)
    else:
        current_reconnect_delay = INITIAL_RECONNECT_DELAY

    last_reconnect_attempt_time = now

    with reconnect_timer_lock:
        if reconnect_timer and reconnect_timer.is_alive():
            return

        print(
            (
                "Radio disconnect detected. Reconnecting in "
                f"{current_reconnect_delay:.1f} seconds..."
            ),
            file=sys.stderr,
        )

        def do_reconnect():
            global reconnect_timer
            global current_db_name, current_db_stationuuid
            with reconnect_timer_lock:
                reconnect_timer = None

            if not is_intentionally_stopped and current_radio_url:
                print(f"Reconnecting to {current_radio_url}...", file=sys.stderr)
                play_radio_station(
                    current_radio_url,
                    name=current_db_name or "",
                    stationuuid=current_db_stationuuid or "",
                )

        reconnect_timer = threading.Timer(current_reconnect_delay, do_reconnect)
        reconnect_timer.daemon = True
        reconnect_timer.start()


def meta_callback(event, player_instance):
    global current_track_name
    media = player_instance.get_media()
    if media:
        now_playing = media.get_meta(12)  # vlc.Meta.NowPlaying
        if now_playing:
            current_track_name = now_playing


def attach_player_event_handlers() -> None:
    global player_event_handlers_attached
    if player_event_handlers_attached:
        return

    if player is None:
        return

    event_manager = player.event_manager()
    event_manager.event_attach(vlc.EventType.MediaMetaChanged, meta_callback, player)
    event_manager.event_attach(
        vlc.EventType.MediaPlayerEndReached, reconnect_callback, player
    )
    event_manager.event_attach(
        vlc.EventType.MediaPlayerEncounteredError, reconnect_callback, player
    )
    player_event_handlers_attached = True


@mcp.tool()
def play_radio_station(url: str, name: str = "", stationuuid: str = "") -> dict:
    """
    Play an audio stream from a given URL using VLC.
    Automatically resolves playlists if necessary.

    Args:
        url (str): The stream URL to play
        name (str, optional): The stream name (for history tracking)
        stationuuid (str, optional): Station UUID from Radio Browser metadata

    Returns:
        dict: Success status and message
    """
    global current_track_name, is_intentionally_stopped, current_radio_url
    global current_reconnect_delay, reconnect_timer
    global current_db_url, current_db_name, current_db_stationuuid
    global playback_start_time, last_db_update_time, tracking_timer

    # If already playing something else, commit its duration first
    _update_duration()

    # Clear old tracking timer
    with tracking_timer_lock:
        if tracking_timer:
            tracking_timer.cancel()
            tracking_timer = None

    current_track_name = None
    is_intentionally_stopped = False
    current_reconnect_delay = INITIAL_RECONNECT_DELAY  # Reset delay on manual play

    with reconnect_timer_lock:
        if reconnect_timer and reconnect_timer.is_alive():
            reconnect_timer.cancel()
        reconnect_timer = None

    player_error = _ensure_player_ready()
    if player_error:
        return {"success": False, "error": player_error}

    try:
        resolved_url = resolve_stream_url(url)
        if not stationuuid:
            try:
                stationuuid = db.find_stationuuid_by_url(resolved_url)
            except Exception:
                stationuuid = ""

        current_db_url = resolved_url
        current_db_name = name
        current_db_stationuuid = stationuuid
        current_radio_url = resolved_url
        now = time.time()
        playback_start_time = now
        last_db_update_time = now

        # Start the periodic background tracking loop
        if ENABLE_BACKGROUND_TRACKING:
            with tracking_timer_lock:
                tracking_timer = threading.Timer(TRACKING_INTERVAL, _update_duration)
                tracking_timer.daemon = True
                tracking_timer.start()

        media = vlc_instance.media_new(resolved_url)
        player.set_media(media)

        # Hook metadata/reconnect events only once for this player instance.
        attach_player_event_handlers()

        player.play()
        return {"success": True, "message": f"Started playback of {resolved_url}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to start playback: {str(e)}"}


@mcp.tool()
def stop_radio() -> dict:
    """
    Stops the currently playing radio station.

    Returns:
        dict: Success status and message
    """
    global is_intentionally_stopped
    global current_db_url, current_db_name, current_db_stationuuid
    global playback_start_time, last_db_update_time, tracking_timer

    # Commit final duration and stop background tracker
    _update_duration()
    with tracking_timer_lock:
        if tracking_timer:
            tracking_timer.cancel()
            tracking_timer = None

    current_db_url = None
    current_db_stationuuid = None
    playback_start_time = None
    last_db_update_time = None

    is_intentionally_stopped = True
    try:
        player_error = _ensure_player_ready()
        if player_error:
            return {"success": False, "error": player_error}
        player.stop()
        return {"success": True, "message": "Stopped playback"}
    except Exception as e:
        return {"success": False, "error": f"Failed to stop playback: {str(e)}"}


@mcp.tool()
def get_radio_status() -> dict:
    """
    Get the current playback status of the radio station.

    Returns:
        dict: The current state, URL, and track info of the playing radio station
    """
    try:
        player_error = _ensure_player_ready()
        if player_error:
            return {"success": False, "error": player_error}
        state = player.get_state()
        media = player.get_media()

        # Get dynamic track info
        global current_track_name

        current_url = None
        now_playing = None
        title = None

        if media:
            current_url = media.get_mrl()

            # 1. First try to get async track name from our event hook.
            if "current_track_name" in globals() and current_track_name:
                now_playing = current_track_name
            else:
                # 2. Extract synchronous metadata
                meta_now_playing = media.get_meta(12)  # vlc.Meta.NowPlaying
                meta_title = media.get_meta(0)  # vlc.Meta.Title

                if meta_now_playing:
                    now_playing = meta_now_playing

                if meta_title:
                    title = meta_title

                # Fallback: if title looks like "Artist - Song", reuse it.
                if not now_playing and title and " - " in title:
                    now_playing = title

        return {
            "success": True,
            "status": get_playstate_str(state),
            "url": current_url,
            "now_playing": now_playing,
            "title": title,
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to get status: {str(e)}"}


@mcp.tool()
def set_radio_volume(volume: int) -> dict:
    """
    Set the volume of the radio player.

    Args:
        volume (int): Volume level from 0 to 100.

    Returns:
        dict: Success status and current volume
    """
    try:
        player_error = _ensure_player_ready()
        if player_error:
            return {"success": False, "error": player_error}
        # Clamp between 0 and 100
        vol = max(0, min(100, volume))
        player.audio_set_volume(vol)
        return {"success": True, "message": f"Volume set to {vol}%"}
    except Exception as e:
        return {"success": False, "error": f"Failed to set volume: {str(e)}"}


@mcp.tool()
def get_radio_volume() -> dict:
    """
    Get the current volume of the radio player.

    Returns:
        dict: Success status and current volume level
    """
    try:
        player_error = _ensure_player_ready()
        if player_error:
            return {"success": False, "error": player_error}
        vol = player.audio_get_volume()
        return {"success": True, "volume": vol}
    except Exception as e:
        return {"success": False, "error": f"Failed to get volume: {str(e)}"}


@mcp.tool()
def add_favorite_station(url: str, name: str = "", stationuuid: str = "") -> dict:
    """
    Add a radio station to favorites.
    """
    try:
        resolved_url = resolve_stream_url(url)
        if not stationuuid:
            stationuuid = db.find_stationuuid_by_url(resolved_url)
        db.add_favorite(resolved_url, name, stationuuid)
        return {
            "success": True,
            "message": f"Added to favorites: {name or resolved_url}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def remove_favorite_station(url: str) -> dict:
    """
    Remove a radio station from favorites.
    """
    try:
        db.remove_favorite(url)
        return {"success": True, "message": f"Removed from favorites: {url}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_favorite_stations() -> dict:
    """
    Get the list of favorite radio stations.
    """
    try:
        return {"success": True, "favorites": db.get_favorites()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_my_recent_stations(limit: int = 10) -> dict:
    """
    Get the most recently played radio stations from personal history.
    """
    try:
        return {"success": True, "recent": db.get_my_recent_stations(limit)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def get_my_top_stations(limit: int = 10) -> dict:
    """
    Get personal top radio stations by total listening duration.
    """
    try:
        return {"success": True, "top": db.get_my_top_stations(limit)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def get_my_top_tags(limit: int = 10) -> dict:
    """
    Get personal top tags aggregated from listened stations with cached station metadata.
    """
    try:
        safe_limit = max(1, min(1000, int(limit)))
        rows = db.get_listened_stations_with_tags()

        tag_scores: dict[str, float] = {}
        tag_station_counts: dict[str, int] = {}
        stations_considered = 0
        stations_with_tags = 0

        for row in rows:
            duration = float(row.get("listen_duration", 0) or 0)
            if duration <= 0:
                continue

            stations_considered += 1
            tags = _parse_tags(row.get("tags_raw", ""))
            if not tags:
                continue

            stations_with_tags += 1
            for tag in tags:
                tag_scores[tag] = tag_scores.get(tag, 0.0) + duration
                tag_station_counts[tag] = tag_station_counts.get(tag, 0) + 1

        top_tags = sorted(tag_scores.items(), key=lambda x: (-x[1], x[0]))[:safe_limit]
        result = [
            {
                "tag": tag,
                "score": round(score, 2),
                "stations_count": tag_station_counts.get(tag, 0),
            }
            for tag, score in top_tags
        ]

        return {
            "success": True,
            "top_tags": result,
            "meta": {
                "limit": safe_limit,
                "stations_considered": stations_considered,
                "stations_with_cached_tags": stations_with_tags,
                "stations_missing_tags": max(0, stations_considered - stations_with_tags),
            },
        }
    except Exception as e:
        return {"success": False, "top_tags": [], "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
