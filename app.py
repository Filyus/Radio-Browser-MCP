import json
import random
import socket

import requests

USER_AGENT = "RadioBrowserMCP/1.0.0"

_cached_servers = []

def get_radiobrowser_base_urls():
    """
    Get all base urls of all currently available radiobrowser servers
    """
    global _cached_servers
    if _cached_servers:
        return _cached_servers

    hosts = []
    # Try the official discovery endpoint first
    try:
        response = requests.get(
            "https://de1.api.radio-browser.info/json/servers",
            headers={"User-Agent": USER_AGENT},
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
        for server in data:
            hosts.append(server["name"])
    except Exception:
        pass  # Silently fail to fallback

    # Fallback to DNS round-robin if the endpoint failed
    if not hosts:
        try:
            ips = socket.getaddrinfo(
                "all.api.radio-browser.info", 80, 0, 0, socket.IPPROTO_TCP
            )
            for ip_tupple in ips:
                ip = ip_tupple[4][0]
                try:
                    host_addr = socket.gethostbyaddr(ip)
                    if host_addr[0] not in hosts:
                        hosts.append(host_addr[0])
                except Exception:
                    continue
        except Exception:
            pass

    # Ensure we always have backups
    fallbacks = [
        "de1.api.radio-browser.info",
        "nl1.api.radio-browser.info",
        "at1.api.radio-browser.info",
        "fr1.api.radio-browser.info",
        "us1.api.radio-browser.info",
        "ca1.api.radio-browser.info",
    ]
    for fb in fallbacks:
        if fb not in hosts:
            hosts.append(fb)

    hosts = list(set(hosts))
    hosts.sort()
    _cached_servers = [f"https://{h}" for h in hosts]
    return _cached_servers


def download_uri(uri, param):
    """
    Download file with the correct headers set
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    if param is None:
        response = requests.get(uri, headers=headers, timeout=5.0)
    else:
        response = requests.post(uri, headers=headers, json=param, timeout=5.0)
    response.raise_for_status()
    return response.content


def download_radiobrowser(path, param):
    """
    Download file with relative url from a random api server with failover.
    """
    servers = get_radiobrowser_base_urls()
    random.shuffle(servers)

    errors = []
    for server_base in servers:
        uri = server_base + path
        try:
            return download_uri(uri, param)
        except Exception as e:
            err_msg = str(e)
            if "urlopen error" in err_msg:
                # Simplify DNS/connection errors
                short_err = err_msg.split("] ")[-1] if "]" in err_msg else err_msg
                errors.append(f"{server_base}: {short_err}")
            else:
                errors.append(f"{server_base}: {err_msg}")
            continue

    # If we get here, all mirrors failed
    unique_errors = list(set(errors))
    error_summary = " | ".join(unique_errors)
    raise Exception(f"All Radio-Browser mirrors failed: {error_summary}")


def get_radiobrowser_stats():
    """
    Get Radio Browser statistics

    Returns:
    dict: Statistics about the Radio Browser database
    """
    stats = download_radiobrowser("/json/stats", None)
    return json.loads(stats)


def search_stations_by_country(country_code):
    """
    Search radio stations by country code

    Args:
    country_code (str): Two-letter country code (e.g., 'US', 'DE', 'TR')

    Returns:
    list: List of radio stations in the specified country
    """
    stations = download_radiobrowser(
        f"/json/stations/bycountrycodeexact/{country_code}", None
    )
    return json.loads(stations)


def search_stations_by_name(name):
    """
    Search radio stations by name

    Args:
    name (str): Name or partial name of the radio station

    Returns:
    list: List of radio stations matching the search term
    """
    return search_stations({"name": name})


def search_stations_by_tag(tag):
    """
    Search radio stations by tag (genre)

    Args:
    tag (str): Tag or genre to search for

    Returns:
    list: List of radio stations matching the tag
    """
    return search_stations({"tag": tag})


def search_stations(params):
    """
    Search stations by parameters accepted by /json/stations/search.

    Args:
    params (dict): Search parameters (e.g. {"name": "BBC"}, {"tag": "jazz"})

    Returns:
    list: List of matching radio stations
    """
    stations = download_radiobrowser("/json/stations/search", params)
    return json.loads(stations)


def get_top_voted_stations(limit=10):
    """
    Get the top voted stations from the Radio Browser API
    """
    stations = download_radiobrowser(f"/json/stations/topvote/{limit}", None)
    return json.loads(stations)


def get_top_clicked_stations(limit=10):
    """
    Get the most clicked stations from the Radio Browser API
    """
    stations = download_radiobrowser(f"/json/stations/topclick/{limit}", None)
    return json.loads(stations)


def get_available_tags(limit=100, order="stationcount", reverse=True):
    """
    Get available tags from the Radio Browser API.

    Args:
    limit (int): Maximum number of tags to return
    order (str): Sort field ("stationcount" or "name")
    reverse (bool): Descending order if True

    Returns:
    list: List of tags with counters
    """
    tags = download_radiobrowser(
        "/json/tags",
        {
            "limit": int(limit),
            "order": order,
            "reverse": bool(reverse),
            "hidebroken": True,
        },
    )
    return json.loads(tags)
