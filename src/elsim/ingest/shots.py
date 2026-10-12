"""Fetches one game's shots from the league's live host.

This endpoint is not in the league's API documentation, so the whole shot
module sits behind the enable_shot_data setting and everything else works
without it.
"""

from pathlib import Path

from elsim.ingest.http_cache import fetch

URL = "https://live.euroleague.net/api/Points"


def fetch_shots(season: str, game_code: int, settings: dict) -> bytes:
    cache_path = Path(settings["raw_dir"]) / "shots" / season / f"{game_code}.json"
    return fetch(URL, {"gamecode": game_code, "seasoncode": season}, cache_path, settings)
