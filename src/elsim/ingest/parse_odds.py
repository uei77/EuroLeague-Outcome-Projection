"""Matches odds snapshot events to league games and flattens bookmaker prices."""

import csv
from datetime import datetime, timedelta
from pathlib import Path

# A snapshot event and a league game are the same game when home and away
# teams agree and the start times are within this window.
MAX_START_DIFFERENCE = timedelta(hours=36)


def load_aliases(source: str) -> dict[str, str]:
    """Return alias -> league team code for one source, from the hand-checked file."""
    with open(Path("config") / "team_aliases.csv", newline="", encoding="utf-8") as f:
        return {row["alias"]: row["team_code"] for row in csv.DictReader(f) if row["source"] == source}


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def match_game(event: dict, aliases: dict[str, str], games: list[dict]) -> int:
    """Return the league game code for one snapshot event.

    Team names are matched only through the alias file, never by similarity.
    Anything that does not match exactly one game raises.
    """
    for side in ("home_team", "away_team"):
        if event[side] not in aliases:
            raise ValueError(
                f"Unknown team name from The Odds API: {event[side]!r}. Add it to config/team_aliases.csv."
            )
    home, away = aliases[event["home_team"]], aliases[event["away_team"]]
    start = _time(event["commence_time"])
    found = [
        game["gameCode"]
        for game in games
        if game["local"]["club"]["code"] == home
        and game["road"]["club"]["code"] == away
        and abs(_time(game["utcDate"]) - start) <= MAX_START_DIFFERENCE
    ]
    if len(found) != 1:
        raise ValueError(
            f"{event['home_team']} v {event['away_team']} at {event['commence_time']} matches {len(found)} league games."
        )
    return found[0]


def price_rows(snapshot: dict, aliases: dict[str, str], games: list[dict]) -> list[list]:
    """Return one row per game and bookmaker:
    [snapshot_utc, game_code, bookmaker, home_price, away_price]."""
    rows = []
    for event in snapshot["events"]:
        game_code = match_game(event, aliases, games)
        for bookmaker in event["bookmakers"]:
            for market in bookmaker["markets"]:
                if market["key"] != "h2h":
                    continue
                prices = {outcome["name"]: outcome["price"] for outcome in market["outcomes"]}
                rows.append(
                    [
                        snapshot["snapshot_utc"],
                        game_code,
                        bookmaker["key"],
                        prices[event["home_team"]],
                        prices[event["away_team"]],
                    ]
                )
    return rows
