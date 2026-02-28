# Radio Browser MCP

A modern Model Context Protocol (MCP) server that provides access to the Radio Browser API and directly streams internet radio stations using VLC.

## Features

### 🔧 Radio Discovery Tools
- **`get_radio_stats()`**: Database statistics (stations, countries, tags).
- **`search_stations_by_country_code(country_code)`**: Discovery by ISO code (e.g., 'US', 'GB').
- **`search_stations_by_station_name(name)`**: Fuzzy search for specific stations.
- **`search_stations_by_tag(tag)`**: Search for stations by genre or tag (e.g., 'chillout', 'jazz', 'rock').
- **`search_global_top_voted_stations(limit)`**: Get the top voted stations globally from the API.
- **`search_global_top_clicked_stations(limit)`**: Get the most clicked stations globally from the API.
- **`get_available_servers()`**: API server discovery and failover info.

### ⭐ Favorites & Personal History
- **`add_favorite_station(url, [name])`**: Add a radio station to your personal favorites list.
- **`remove_favorite_station(url)`**: Remove a station from favorites.
- **`get_favorite_stations()`**: List all saved favorite stations.
- **`get_my_recent_stations([limit])`**: View your most recently played stations.
- **`get_my_top_stations([limit])`**: View your personal top stations sorted by total listening duration.

### 🎵 Playback & Control Tools
- **`play_radio_station(url)`**: Stream any radio URL directly to your system speakers. Supports playlist resolution (.m3u, .pls).
- **`stop_radio()`**: Immediate playback termination.
- **`get_radio_status()`**: Returns current station, URL, and **Now Playing** track metadata (updated dynamically).
- **`set_radio_volume(volume)`**: Adjust volume (0-100).
- **`get_radio_volume()`**: Retrieve current volume level.
- **`Automatic Reconnection`**: Smooth playback with exponential backoff for unstable streams (configurable).

---

## 🛠️ Requirements
- **VLC Media Player**: Must be installed on your system.
- **Python 3.10+**

## 🚀 Quick Start (Modern)

The server is optimized for [uv](https://github.com/astral-sh/uv). You can run it without even cloning the repository or managing a virtual environment.

### Using `uvx`
```bash
uvx --from git+https://github.com/Filyus/Radio-Browser-MCP radio-browser-mcp
```

### Local Development
If you have the source code locally, you can run it with:
```bash
uvx --from . radio-browser-mcp
```

---

## ⚙️ Configuration

The server supports several environment variables to tune the automatic reconnection behavior and listening history tracking:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `RADIO_INITIAL_RECONNECT_DELAY` | `0.1` | Starting delay in seconds for reconnection attempts. |
| `RADIO_MAX_RECONNECT_DELAY` | `30.0` | Maximum capped delay for exponential backoff (seconds). |
| `RADIO_RECONNECT_BACKOFF_THRESHOLD` | `5.0` | Window (seconds) to detect unstable streams and trigger backoff. |
| `RADIO_ENABLE_BACKGROUND_TRACKING` | `true` | Enable periodic background commits of listening duration to SQLite. |
| `RADIO_TRACKING_INTERVAL` | `60.0` | Interval (seconds) between background duration tracking commits. |

## ⚙️ MCP Configuration

Based on how you installed the server, add one of the following configurations to your MCP client (such as Claude Desktop or `mcp_config.json` for Antigravity AI).

### Option 1: Remote execution (via `uvx`)
This is the recommended approach if you don't want to clone the repository manually. It fetches the code and dependencies automatically.

```json
{
  "mcpServers": {
    "radio-browser": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/Filyus/Radio-Browser-MCP",
        "radio-browser-mcp"
      ],
      "env": {
        "RADIO_INITIAL_RECONNECT_DELAY": "0.1",
        "RADIO_ENABLE_BACKGROUND_TRACKING": "true",
        "RADIO_TRACKING_INTERVAL": "60.0"
      }
    }
  }
}
```

### Option 2: Local execution (via `uv run` / `python`)
If you have cloned the repository locally (e.g., for Antigravity AI or active development), point the configuration to your local script path. Using `uv run` ensures all dependencies are managed automatically.

```json
{
  "mcpServers": {
    "radio-browser": {
      "command": "uv",
      "args": [
        "run",
        "C:\\MCP-Servers\\Radio-Browser-MCP\\server.py"
      ],
      "env": {
        "RADIO_INITIAL_RECONNECT_DELAY": "0.1",
        "RADIO_ENABLE_BACKGROUND_TRACKING": "true",
        "RADIO_TRACKING_INTERVAL": "60.0"
      }
    }
  }
}
```

*(Note: You can replace `"uv", "run"` with `"python"` if you have manually installed dependencies via `pip` into your active environment.)*

---

## 📁 File Structure
- `server.py`: FastMCP server with playback event hooks and history routing.
- `app.py`: Radio Browser API client and playlist resolver.
- `db.py`: SQLite database tracking for favorites and playback metrics (`radio_history.db`).
- `pyproject.toml`: Modern Python project definition.
- `example_usage.py`: Demonstration script.

## 🛡️ Key Technologies
- **VLC (python-vlc)**: Used for high-compatibility audio streaming (HTTPS/HLS/ICY).
- **FastMCP**: High-level MCP framework for tool registration.
- **Ruff**: Ensuring a clean, modernized codebase.

## ⚖️ License
This project is open source. Powered by the free [Radio Browser API](https://www.radio-browser.info/).
