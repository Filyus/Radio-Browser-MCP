# Radio Browser MCP

A modern Model Context Protocol (MCP) server that provides access to the Radio Browser API and directly streams internet radio stations using VLC.

## Features

### 🔧 Radio Discovery Tools
- **`get_radio_stats()`**: Database statistics (stations, countries, tags).
- **`search_stations_by_country_code(country_code)`**: Discovery by ISO code (e.g., 'US', 'GB').
- **`search_stations_by_station_name(name)`**: Fuzzy search for specific stations.
- **`get_available_servers()`**: API server discovery and failover info.

### 🎵 Playback & Control Tools
- **`play_radio_station(url)`**: Stream any radio URL directly to your system speakers. Supports playlist resolution (.m3u, .pls).
- **`stop_radio()`**: Immediate playback termination.
- **`get_radio_status()`**: Returns current station, URL, and **Now Playing** track metadata (updated dynamically).
- **`set_radio_volume(volume)`**: Adjust volume (0-100).
- **`get_radio_volume()`**: Retrieve current volume level.

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

## ⚙️ MCP Configuration

Add this to your MCP configuration file (e.g., `mcp_config.json` or Claude Desktop config):

```json
{
  "mcpServers": {
    "radio-browser": {
      "command": "uvx",
      "args": [
        "--from", "C:\\path\\to\\Radio-Browser-MCP",
        "radio-browser-mcp"
      ]
    }
  }
}
```

---

## 📁 File Structure
- `server.py`: FastMCP server with playback event hooks.
- `app.py`: Radio Browser API client and playlist resolver.
- `pyproject.toml`: Modern Python project definition.
- `example_usage.py`: Demonstration script.

## 🛡️ Key Technologies
- **VLC (python-vlc)**: Used for high-compatibility audio streaming (HTTPS/HLS/ICY).
- **FastMCP**: High-level MCP framework for tool registration.
- **Ruff**: Ensuring a clean, modernized codebase.

## ⚖️ License
This project is open source. Powered by the free [Radio Browser API](https://www.radio-browser.info/).
