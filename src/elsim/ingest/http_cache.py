"""Rate-limited HTTP GET with a disk cache, so no response is fetched twice."""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

_last_request = 0.0


def fetch(url: str, params: dict, cache_path: Path, settings: dict, refresh: bool = False) -> bytes:
    """Return the JSON body for url, reading it from cache_path when present.

    refresh=True fetches again and replaces the cached copy. Use it only for
    data that changes, such as the current season's schedule.

    A response is cached only if it is non-empty, valid JSON. Anything else
    raises, so a bad response can never be mistaken for data later.
    """
    global _last_request
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        return cache_path.read_bytes()

    wait = settings["min_interval_seconds"] - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    full_url = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        full_url,
        headers={"User-Agent": settings["user_agent"], "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    finally:
        _last_request = time.monotonic()

    if not body.strip():
        raise ValueError(f"Empty response from {full_url}")
    json.loads(body)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".part")
    temporary.write_bytes(body)
    temporary.replace(cache_path)
    return body
