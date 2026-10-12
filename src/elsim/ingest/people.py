"""Fetches each club's registered people for a season: players with position
and registration dates, and coaches with their dates."""

from pathlib import Path

from elsim.ingest.http_cache import fetch
from elsim.ingest.schedule import BASE_URL, fetch_schedule


def fetch_people(season: str, settings: dict) -> int:
    """Save one file per club of the season and return the number of clubs.
    The current season is fetched afresh, because registrations change."""
    clubs = sorted(
        {game[side]["club"]["code"] for game in fetch_schedule(season, settings) for side in ("local", "road")}
    )
    refresh = season == settings["current_season"]
    for club in clubs:
        url = f"{BASE_URL}/{settings['competition']}/seasons/{season}/clubs/{club}/people"
        cache_path = Path(settings["raw_dir"]) / "people" / season / f"{club}.json"
        fetch(url, {}, cache_path, settings, refresh)
    return len(clubs)
