"""Schedule context of each game, known as soon as the schedule is: days of
rest since each team's previous EuroLeague game and how far each team
travelled to the venue.

Venue coordinates come from config/venues.csv (city level, entered by hand).
Domestic-league games are not in our data, so rest counts EuroLeague games
only.
"""

import csv
from collections import Counter, defaultdict
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

MAX_REST_DAYS = 4  # four or more days off count as fully rested

CONTEXT_DDL = """season_code VARCHAR, game_code INTEGER, home_rest_days INTEGER, away_rest_days INTEGER,
    home_travel_km DOUBLE, away_travel_km DOUBLE"""


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (latitude, longitude) points."""
    (lat1, lon1), (lat2, lon2) = ((radians(x), radians(y)) for x, y in (a, b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))


def load_venues() -> dict[str, tuple[float, float]]:
    with open(Path("config") / "venues.csv", newline="", encoding="utf-8") as f:
        return {r["venue_code"]: (float(r["latitude"]), float(r["longitude"])) for r in csv.DictReader(f)}


def build_game_context(db, venues: dict[str, tuple[float, float]], require_all: bool = True) -> None:
    """Create the game_context table. A team's base in a season is the venue
    of most of its regular-season home games in the published schedule; its
    travel to a game is the distance from that base to the game's venue. A
    venue missing from venues is reported, never guessed: it stops the load,
    or with require_all=False its games get no travel distance."""
    games = db.execute(
        """SELECT season_code, game_code, tipoff_utc, home_code, away_code, venue_code, phase
           FROM games WHERE status <> 'Cancelled' ORDER BY tipoff_utc, game_code"""
    ).fetchall()
    missing = sorted({g[5] for g in games if g[5] not in venues})
    if missing and require_all:
        raise SystemExit(f"config/venues.csv has no coordinates for venues {missing}. Add them before loading.")
    if missing:
        print(f"{len(missing)} venues have no coordinates; their games get no travel distance", flush=True)
    home_venues = defaultdict(Counter)
    for season, _, _, home, _, venue, phase in games:
        if phase == "RS" and venue in venues:
            home_venues[(season, home)][venue] += 1
    base = {key: venues[counts.most_common(1)[0][0]] for key, counts in home_venues.items()}

    rows, last = [], {}
    for season, game, tipoff, home, away, venue, _ in games:
        rest = []
        for team in (home, away):
            previous = last.get((season, team))
            rest.append(
                MAX_REST_DAYS if previous is None else min((tipoff.date() - previous.date()).days, MAX_REST_DAYS)
            )
            last[(season, team)] = tipoff
        travel = [
            distance_km(base[(season, team)], venues[venue]) if (season, team) in base and venue in venues else None
            for team in (home, away)
        ]
        rows.append([season, game, *rest, *travel])
    db.execute(f"CREATE OR REPLACE TABLE game_context ({CONTEXT_DDL})")
    db.executemany("INSERT INTO game_context VALUES (?, ?, ?, ?, ?, ?)", rows)
