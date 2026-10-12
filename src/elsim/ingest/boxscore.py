"""Fetches one game's box score from the league's live host."""

from pathlib import Path

from elsim.ingest.http_cache import fetch

URL = "https://live.euroleague.net/api/Boxscore"


def fetch_boxscore(season: str, game_code: int, settings: dict) -> bytes:
    cache_path = Path(settings["raw_dir"]) / "boxscore" / season / f"{game_code}.json"
    return fetch(URL, {"gamecode": game_code, "seasoncode": season}, cache_path, settings)
