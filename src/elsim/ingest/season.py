"""Fetches box score and play-by-play for every played game of a season, and
shots too when the shot module is on."""

from elsim.ingest.boxscore import fetch_boxscore
from elsim.ingest.playbyplay import fetch_playbyplay
from elsim.ingest.schedule import fetch_schedule
from elsim.ingest.shots import fetch_shots


def fetch_season(season: str, settings: dict) -> list[tuple[int, str]]:
    """Return the games that could not be fetched, as (game code, error).

    A failed game is reported and skipped, never cached, so running the same
    command again retries only the failures.
    """
    played = sorted(game["gameCode"] for game in fetch_schedule(season, settings) if game["played"])
    failures = []
    consecutive = 0
    for count, game_code in enumerate(played, start=1):
        try:
            fetch_boxscore(season, game_code, settings)
            fetch_playbyplay(season, game_code, settings)
            if settings["enable_shot_data"]:
                fetch_shots(season, game_code, settings)
            consecutive = 0
        except (OSError, ValueError) as error:
            failures.append((game_code, str(error)))
            print(f"{season} game {game_code} FAILED: {error}", flush=True)
            consecutive += 1
            if consecutive == 10:
                # The host is refusing us or the network is down. Do not keep knocking.
                raise SystemExit(
                    f"Stopped: 10 games in a row failed in {season}. Nothing was lost; run again later."
                ) from error
        if count % 25 == 0 or count == len(played):
            print(f"{season}: {count} of {len(played)} played games done", flush=True)
    return failures
