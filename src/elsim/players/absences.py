"""Known player absences, supplied by hand in config/absences.csv, and what
an absence is worth to a team.

There is no injury feed. The file is filled in before a round from the
league's own injury report and club announcements, each line with its
source. A player is treated as absent for every game that tips off on or
before his "until" date.
"""

import csv
from datetime import datetime
from pathlib import Path

import numpy as np

from elsim.models.state_space import run
from elsim.players.breakout import ROTATION_LEVEL


def load_absences(db, season: str, file: str = "config/absences.csv") -> dict[str, datetime]:
    """Return {player_id: last day absent}. A name that is not registered
    with that club this season stops the run: names are never guessed. An
    empty file name (a competition kept without absences) gives none."""
    path = Path(file)
    if not file or not path.exists():
        return {}
    absent = {}
    with open(path, newline="", encoding="utf-8") as f:
        for line in csv.DictReader(f):
            found = db.execute(
                "SELECT DISTINCT player_id FROM people WHERE season_code = ? AND team_code = ? AND type = 'J' AND name = ?",
                [season, line["team_code"], line["player_name"]],
            ).fetchall()
            if len(found) != 1:
                raise SystemExit(
                    f"{file}: {line['player_name']!r} is not registered with "
                    f"{line['team_code']} in {season}. Use the name exactly as the league writes it."
                )
            absent[found[0][0]] = datetime.strptime(line["until"], "%Y-%m-%d").replace(hour=23, minute=59)
    return absent


CURVE_LENGTH = 40  # games; beyond this the last value is used
CURVE_START = 10  # the trial drop begins at a team's tenth game of a season


def absorption_curve(games: list, params, season_start: dict) -> list[float]:
    """Return, for k = 0, 1, 2, ..., the share of a lasting drop in a team's
    strength that the rating model has already learned after the team has
    played k games with it.

    The rating model also learns from results, so a long absence shows up in
    the team's rating by itself. Without this curve it would be counted
    twice: once in the rating and once in the absence shift. The curve is
    measured, not assumed: one team's results are lowered by a fixed amount
    from a given game on, and the model's forecasts with and without that
    change are compared. The filter is linear, so the share does not depend
    on the size of the drop.
    """
    played = [g for g in games if g.home_per_100 is not None]
    seasons = sorted({g.season for g in played})
    season = seasons[-2] if len(seasons) > 1 else seasons[-1]  # the last full season
    counts = {}
    for g in played:
        if g.season == season:
            counts[g.home] = counts.get(g.home, 0) + 1
            counts[g.away] = counts.get(g.away, 0) + 1
    team = max(sorted(counts), key=counts.get)

    drop = 10.0
    changed, own_games, seen = [], [], 0
    for i, g in enumerate(played):
        if g.season == season and team in (g.home, g.away):
            seen += 1
            if seen > CURVE_START:
                own_games.append(i)
                sign = -1.0 if g.home == team else 1.0
                g = g._replace(
                    home_per_100=g.home_per_100 + sign * drop / 2, away_per_100=g.away_per_100 - sign * drop / 2
                )
        changed.append(g)
    before, after = run(played, params, season_start), run(changed, params, season_start)
    curve = []
    for i in own_games[: CURVE_LENGTH + 1]:
        sign = 1.0 if played[i].home == team else -1.0
        curve.append(sign * (before[i].margin_per_100 - after[i].margin_per_100) / drop)
    return curve


def mark_absent(candidates: list[dict], absent: dict[str, datetime], curve: list[float]) -> None:
    """Set on every candidate row, in playing order:
    absent          for a finished game, the player did not play; for a
                    game to come, the file says he will not
    absence_weight  the share of his absence the rating model has not yet
                    learned, from how many games in a row he has missed
    """
    streak = {}
    for r in candidates:
        key = (r["season_code"], r["player_id"])
        if r["game_played"]:
            r["absent"] = not r["played"]
        else:
            r["absent"] = r["player_id"] in absent and r["asof_utc"] <= absent[r["player_id"]]
        missed = streak.get(key, 0)
        r["absence_weight"] = 1.0 - curve[min(missed, len(curve) - 1)]
        streak[key] = missed + 1 if r["absent"] else 0


def missing_level(candidates: list[dict]) -> dict[tuple[str, int, str], float]:
    """Return, per (season, game, team), the summed level of absent rotation
    players, each counted only for the share the rating model has not yet
    learned."""
    missing = {}
    for r in candidates:
        if r["absent"] and r["level"] >= ROTATION_LEVEL:
            key = (r["season_code"], r["game_code"], r["team_code"])
            missing[key] = missing.get(key, 0.0) + r["level"] * r["absence_weight"]
    return missing


def fit_absence_effect(missing: dict, history: list[dict]) -> float:
    """Return how many points per 100 possessions a team's margin changed,
    beyond the rating model's forecast, per point of missing level.

    history holds finished games with home, away, the forecast margin and the
    actual margin (both per 100 possessions). The fit is a line through the
    origin on (home missing minus away missing). It is learned from who did
    not play in past games, whatever the reason.
    """
    x = np.array(
        [
            missing.get((g["season_code"], g["game_code"], g["home_code"]), 0.0)
            - missing.get((g["season_code"], g["game_code"], g["away_code"]), 0.0)
            for g in history
        ]
    )
    y = np.array([g["actual_margin"] - g["forecast_margin"] for g in history])
    return float(x @ y / (x @ x))


RUN_ABSENCES_DDL = """CREATE TABLE IF NOT EXISTS run_absences (
    run_id VARCHAR, player_id VARCHAR, until TIMESTAMP)"""


def store_absences(db, run_id: str, absent: dict[str, datetime]) -> None:
    """Record the absences a run was made with, so its numbers can be explained later."""
    db.execute(RUN_ABSENCES_DDL)
    for player_id, until in absent.items():
        db.execute("INSERT INTO run_absences VALUES (?, ?, ?)", [run_id, player_id, until])
