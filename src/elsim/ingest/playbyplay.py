"""Fetches one game's play-by-play from the league's live host."""

from pathlib import Path

from elsim.ingest.http_cache import fetch

URL = "https://live.euroleague.net/api/PlaybyPlay"


def fetch_playbyplay(season: str, game_code: int, settings: dict) -> bytes:
    cache_path = Path(settings["raw_dir"]) / "playbyplay" / season / f"{game_code}.json"
    return fetch(URL, {"gamecode": game_code, "seasoncode": season}, cache_path, settings)
