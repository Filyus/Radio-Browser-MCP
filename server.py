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
import urllib.request
from typing import Any

import vlc
from mcp.server.fastmcp import FastMCP

from app import (
    get_radiobrowser_base_urls,
    get_radiobrowser_stats,
    search_stations_by_country,
    search_stations_by_name,
    search_stations_by_tag as app_search_by_tag,
)

# Initialize MCP server
mcp = FastMCP("radio-browser-mcp")

# Global VLC instance and player
vlc_instance = vlc.Instance("--no-video")
player = vlc_instance.media_player_new()

is_intentionally_stopped = False
current_radio_url = None

# Reconnection configuration (normalized as constants)
INITIAL_RECONNECT_DELAY = float(os.environ.get("RADIO_INITIAL_RECONNECT_DELAY", 0.1))
MAX_RECONNECT_DELAY = float(os.environ.get("RADIO_MAX_RECONNECT_DELAY", 30.0))
RECONNECT_BACKOFF_THRESHOLD = float(os.environ.get("RADIO_RECONNECT_BACKOFF_THRESHOLD", 5.0))

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


@mcp.tool()
def get_radio_stats() -> dict:
    """
    Get Radio Browser statistics including total number of stations, countries, and other metrics.

    Returns:
        dict: Statistics about the Radio Browser database
    """
    try:
        result = get_radiobrowser_stats()
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
        servers = get_radiobrowser_base_urls()
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
        result = search_stations_by_country(country_code.upper())
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
        result = search_stations_by_name(name)
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
        result = app_search_by_tag(tag)
        return {"success": True, "stations": result}
    except Exception as e:
        return {"success": False, "stations": [], "error": str(e)}

def resolve_stream_url(url: str) -> str:
    """Attempts to resolve a playlist (.m3u, .pls) to its actual stream URL."""
    try:
        # Check if it's a known playlist format or if we should peek
        if url.endswith(".m3u") or url.endswith(".pls") or url.endswith(".m3u8"):
            req = urllib.request.Request(
                url, headers={"User-Agent": "RadioBrowserMCP/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5.0) as response:
                content = response.read().decode("utf-8", errors="ignore").splitlines()
                for line in content:
                    line = line.strip()
                    if line.startswith("http"):
                        return line
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
            with reconnect_timer_lock:
                reconnect_timer = None

            if not is_intentionally_stopped and current_radio_url:
                print(f"Reconnecting to {current_radio_url}...", file=sys.stderr)
                play_radio_station(current_radio_url)

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

    event_manager = player.event_manager()
    event_manager.event_attach(vlc.EventType.MediaMetaChanged, meta_callback, player)
    event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, reconnect_callback, player)
    event_manager.event_attach(
        vlc.EventType.MediaPlayerEncounteredError, reconnect_callback, player
    )
    player_event_handlers_attached = True


@mcp.tool()
def play_radio_station(url: str) -> dict:
    """
    Play an audio stream from a given URL using VLC.
    Automatically resolves playlists if necessary.

    Args:
        url (str): The stream URL to play

    Returns:
        dict: Success status and message
    """
    global current_track_name, is_intentionally_stopped, current_radio_url
    global current_reconnect_delay, reconnect_timer
    current_track_name = None
    is_intentionally_stopped = False
    current_radio_url = url
    current_reconnect_delay = INITIAL_RECONNECT_DELAY  # Reset delay on manual play

    with reconnect_timer_lock:
        if reconnect_timer and reconnect_timer.is_alive():
            reconnect_timer.cancel()
        reconnect_timer = None

    try:
        resolved_url = resolve_stream_url(url)
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
    is_intentionally_stopped = True
    try:
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
        state = player.get_state()
        media = player.get_media()

        # Get dynamic track info
        global current_track_name

        current_url = None
        now_playing = None
        title = None

        if media:
            current_url = media.get_mrl()

            # 1. First try to get the asynchronously updated track name from our event hook
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

                # Fallback heuristic: If NowPlaying is empty but Title looks like "Artist - Song", use it
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
        vol = player.audio_get_volume()
        return {"success": True, "volume": vol}
    except Exception as e:
        return {"success": False, "error": f"Failed to get volume: {str(e)}"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
