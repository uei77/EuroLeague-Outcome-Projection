"""Fetches a season's game list from the league's api-live host."""

import json
from pathlib import Path

from elsim.ingest.http_cache import fetch

BASE_URL = "https://api-live.euroleague.net/v2/competitions"


def fetch_schedule(season: str, settings: dict) -> list[dict]:
    """Return every game of the season. The current season is fetched afresh
    each time, because its games change from unplayed to played."""
    url = f"{BASE_URL}/{settings['competition']}/seasons/{season}/games"
    cache_path = Path(settings["raw_dir"]) / "schedule" / f"{season}.json"
    refresh = season == settings["current_season"]
    schedule = json.loads(fetch(url, {"limit": 1000}, cache_path, settings, refresh))
    if len(schedule["data"]) != schedule["total"]:
        raise ValueError(f"Schedule {season} is incomplete: {len(schedule['data'])} of {schedule['total']} games")
    return schedule["data"]
