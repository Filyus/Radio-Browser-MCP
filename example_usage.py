#!/usr/bin/env python3
"""
Example usage of Radio Browser MCP
This script demonstrates how to use the Radio Browser MCP tools
"""

import os
import sys

# Add the current directory to the path so we can import our server
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import (
    get_available_servers,
    get_radio_stats,
    get_radio_status,
    get_radio_volume,
    play_radio_station,
    search_stations_by_country_code,
    search_stations_by_station_name,
    set_radio_volume,
    stop_radio,
)


def demo_radio_browser_mcp():
    """Demonstrate Radio Browser MCP functionality"""

    print("🎵 Radio Browser MCP Demo")
    print("=" * 50)

    # 1. Get Radio Browser statistics
    print("\n📊 Getting Radio Browser Statistics...")
    stats_response = get_radio_stats()
    if stats_response.get("success"):
        stats = stats_response.get("stats", {})
        print(f"   📻 Total Stations: {stats.get('stations', 'N/A'):,}")
        print(f"   🌍 Countries: {stats.get('countries', 'N/A')}")
        print(f"   🗣️ Languages: {stats.get('languages', 'N/A')}")
        print(f"   👆 Clicks Last Hour: {stats.get('clicks_last_hour', 'N/A'):,}")
    else:
        print(f"   ❌ Error: {stats_response.get('error', 'Unknown error')}")

    # 2. Get available servers
    print("\n🌐 Getting Available Servers...")
    servers_response = get_available_servers()
    servers = servers_response.get("servers", [])
    if servers_response.get("success"):
        print(f"   Found {len(servers)} servers:")
        for i, server in enumerate(servers[:3], 1):
            print(f"   {i}. {server}")
        if len(servers) > 3:
            print(f"   ... and {len(servers) - 3} more")
    else:
        print(f"   ❌ Error: {servers_response.get('error', 'Unknown error')}")

    # 3. Search stations by country (Turkey)
    print("\n🇹🇷 Searching Turkish Radio Stations...")
    tr_response = search_stations_by_country_code("TR")
    tr_stations = tr_response.get("stations", [])
    if tr_response.get("success") and len(tr_stations) > 0:
        print(f"   Found {len(tr_stations)} Turkish stations")
        print("   Top 5 Turkish stations:")
        for i, station in enumerate(tr_stations[:5], 1):
            name = station.get("name", "Unknown")
            url = station.get("url", "No URL")
            print(f"   {i}. {name}")
            print(f"      🔗 {url}")
    else:
        print("   ❌ No Turkish stations found or error occurred")

    # 4. Search stations by name (BBC)
    print("\n🎙️ Searching BBC Radio Stations...")
    bbc_response = search_stations_by_station_name("BBC")
    bbc_stations = bbc_response.get("stations", [])
    if bbc_response.get("success") and len(bbc_stations) > 0:
        print(f"   Found {len(bbc_stations)} BBC stations")
        print("   Top 5 BBC stations:")
        for i, station in enumerate(bbc_stations[:5], 1):
            name = station.get("name", "Unknown")
            country = station.get("country", "Unknown")
            print(f"   {i}. {name} ({country})")
    else:
        print("   ❌ No BBC stations found or error occurred")

    # 5. Search for rock music stations
    print("\n🎸 Searching Rock Music Stations...")
    rock_response = search_stations_by_station_name("Rock")
    rock_stations = rock_response.get("stations", [])
    if rock_response.get("success") and len(rock_stations) > 0:
        print(f"   Found {len(rock_stations)} rock stations")
        print("   Top 3 rock stations:")
        for i, station in enumerate(rock_stations[:3], 1):
            name = station.get("name", "Unknown")
            country = station.get("country", "Unknown")
            tags = station.get("tags", "")
            print(f"   {i}. {name} ({country})")
            if tags:
                print(f"      🏷️ Tags: {tags}")
    else:
        print("   ❌ No rock stations found or error occurred")

    # 6. Demonstrate Playback (briefly)
    print("\n🔊 Demonstrating Playback (SomaFM PopTron)...")
    play_result = play_radio_station("http://ice1.somafm.com/poptron-128-mp3")

    if play_result.get("success"):
        print("   ✅ Playback started. Buffering for 10 seconds to catch metadata...")
        import time

        time.sleep(10)

        # Check volume
        vol = get_radio_volume()
        print(f"   🔈 Current Volume: {vol.get('volume')}%")

        # Adjust volume
        print("   🔉 Setting volume to 50%...")
        set_radio_volume(50)

        # Check status and track info
        status = get_radio_status()
        print(f"   📻 Status: {status.get('status')}")
        print(f"   🎵 Now Playing: {status.get('now_playing', 'Unknown')}")

        print("   🛑 Stopping playback...")
        stop_radio()
    else:
        print(f"   ❌ Failed to start playback: {play_result.get('error')}")

    print("\n✅ Demo completed!")
    print("\n💡 You can now use these tools in your MCP-enabled applications!")


if __name__ == "__main__":
    demo_radio_browser_mcp()
