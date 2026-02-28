import json
import random
import socket
import urllib.request

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
        req = urllib.request.Request("https://de1.api.radio-browser.info/json/servers")
        req.add_header("User-Agent", "RadioBrowserMCP/1.0.0")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read())
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
    param_encoded = None
    if param is not None:
        param_encoded = json.dumps(param).encode("utf-8")
    
    req = urllib.request.Request(uri, param_encoded)
    req.add_header("User-Agent", "RadioBrowserMCP/1.0.0")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=5.0) as response:
        return response.read()


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
    stations = download_radiobrowser("/json/stations/search", {"name": name})
    return json.loads(stations)


def search_stations_by_tag(tag):
    """
    Search radio stations by tag (genre)

    Args:
    tag (str): Tag or genre to search for

    Returns:
    list: List of radio stations matching the tag
    """
    stations = download_radiobrowser("/json/stations/search", {"tag": tag})
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
