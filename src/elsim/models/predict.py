"""Forecasts the games not yet played with the published model and stores
them under a run id."""

from elsim import runs
from elsim.models.backtest import START, VARIANTS, as_games, fit, load_context, load_rosters, shrink_context
from elsim.models.state_space import Game, run_with_state

# Every played game in playing order, then the current season's unplayed
# games. A played game without usable data (one game the source returns
# empty) is left out, as are unplayed games of past seasons.
ALL_GAMES_SQL = """
SELECT g.season_code, g.game_code, g.round, g.phase, g.tipoff_utc, g.home_code, g.away_code, g.played,
       g.home_score, g.away_score, g.home_standings_score, g.away_standings_score,
       g.phase = 'FF' AS neutral,
       100.0 * h.points / h.possessions AS home_per_100,
       100.0 * a.points / a.possessions AS away_per_100,
       (fh.pace + fa.pace) / 2 AS pace
FROM games AS g
LEFT JOIN team_game_stats AS h ON h.season_code = g.season_code AND h.game_code = g.game_code AND h.is_home
LEFT JOIN team_game_stats AS a ON a.season_code = g.season_code AND a.game_code = g.game_code AND NOT a.is_home
LEFT JOIN features_team AS fh ON fh.season_code = g.season_code AND fh.game_code = g.game_code AND fh.team_code = g.home_code
LEFT JOIN features_team AS fa ON fa.season_code = g.season_code AND fa.game_code = g.game_code AND fa.team_code = g.away_code
WHERE (g.played AND h.points IS NOT NULL)
   OR (NOT g.played AND g.season_code = ? AND g.status <> 'Cancelled')
ORDER BY g.played DESC, g.tipoff_utc, g.game_code
"""

GAME_PREDICTIONS_DDL = """CREATE TABLE IF NOT EXISTS game_predictions (
    run_id VARCHAR, season_code VARCHAR, game_code INTEGER, p_home DOUBLE,
    expected_margin DOUBLE, margin_sd DOUBLE, model_used VARCHAR)"""

MODEL_USED = "rating model with roster start and roster changes"


def load_inputs(db, current: str, roster_column: str = "available_z") -> tuple[list[dict], list[Game], dict]:
    """Return game rows, the same games as rating model input (with roster
    z-scores at tip-off, see load_rosters), and each team's season-start
    roster z-score."""
    cursor = db.execute(ALL_GAMES_SQL, [current])
    names = [c[0] for c in cursor.description]
    rows = [dict(zip(names, r)) for r in cursor.fetchall()]
    by_game, season_start = load_rosters(db, roster_column)
    return rows, as_games(rows, by_game, load_context(db)), season_start


def predict_upcoming(db, settings: dict) -> dict:
    """Fit the rating model's settings on the completed seasons, run it through
    every played game, forecast every unplayed game of the current season and
    store the forecasts. Returns a dict with:
      run_id           the id of the stored run
      upcoming         one row per unplayed game, with the forecast
      expected_points  for every game, the points the model expected of each
                       team before it, keyed by (season, game, team)
      history          finished games with forecast and actual margin per 100
      model            (games, settings, season start) as given to the rating model
      state            the rating model's belief after every game, played or not
      postseason_shift per team, what the hand-entered absences still running
                       after the last game are worth (points per 100 possessions)

    Each unplayed game is forecast twice: with the players expected to be
    available, and also without the hand-entered absences (p_home_with_absences,
    margin_with_absences, absence_shift in points per 100, home minus away).
    expected_margin and margin_sd are in points, for the two teams' average
    pace so far this season.
    """
    current = settings["current_season"]
    rows, games, season_start = load_inputs(db, current)

    completed = [g for g, r in zip(games, rows) if r["season_code"] < current]
    params = START
    for free in VARIANTS.values():  # the plain model first, then with the roster start
        params = fit(completed, season_start, free, params)
    params = shrink_context(params)

    run_id = runs.record(db, {"model": MODEL_USED, "settings": params._asdict()}, settings["seed"])
    predictions, state = run_with_state(games, params, season_start)
    with_absences, known_state = run_with_state(load_inputs(db, current, "known_absences_z")[1], params, season_start)
    n = len(state.teams)
    margin = lambda x, i: x[i] - x[n + i]  # offence minus points allowed
    postseason_shift = {
        team: margin(known_state.values, i) - margin(state.values, i)
        for i, team in enumerate(state.teams)
        if abs(margin(known_state.values, i) - margin(state.values, i)) > 1e-9
    }
    upcoming, history, expected_points = [], [], {}
    league_pace = sum(r["pace"] for r in rows if r["pace"]) / sum(1 for r in rows if r["pace"])
    for row, prediction, known in zip(rows, predictions, with_absences):
        possessions = (row["pace"] or league_pace) / 100.0  # no pace yet in a season's first games
        expected_points[(row["season_code"], row["game_code"], row["home_code"])] = (
            prediction.home_per_100 * possessions
        )
        expected_points[(row["season_code"], row["game_code"], row["away_code"])] = (
            prediction.away_per_100 * possessions
        )
        if row["played"]:
            history.append(
                {
                    **row,
                    "forecast_margin": prediction.margin_per_100,
                    "actual_margin": row["home_per_100"] - row["away_per_100"],
                }
            )
            continue
        upcoming.append(
            {
                **row,
                "p_home": prediction.p_home,
                "possessions": possessions,
                "margin_per_100": prediction.margin_per_100,
                "margin_sd_per_100": prediction.margin_sd,
                "expected_margin": prediction.margin_per_100 * possessions,
                "margin_sd": prediction.margin_sd * possessions,
                "absence_shift": known.margin_per_100 - prediction.margin_per_100,
                "p_home_with_absences": known.p_home,
                "margin_with_absences": known.margin_per_100 * possessions,
                "home_points": prediction.home_per_100 * possessions,
                "away_points": prediction.away_per_100 * possessions,
                "total_sd": prediction.total_sd * possessions,
            }
        )
    return {
        "run_id": run_id,
        "upcoming": upcoming,
        "expected_points": expected_points,
        "history": history,
        "model": (games, params, season_start),
        "state": state,
        "postseason_shift": postseason_shift,
    }


ABSENCE_SHIFTS_DDL = """CREATE TABLE IF NOT EXISTS absence_shifts (
    run_id VARCHAR, team_code VARCHAR, postseason_shift_per_100 DOUBLE)"""


def store_postseason_shifts(db, run_id: str, shifts: dict[str, float]) -> None:
    """Store, per team, what its known absences that outlast the regular
    season are worth, for the simulator's play-in, playoffs and Final Four."""
    db.execute(ABSENCE_SHIFTS_DDL)
    for team, shift in shifts.items():
        db.execute("INSERT INTO absence_shifts VALUES (?, ?, ?)", [run_id, team, shift])


def store(db, run_id: str, upcoming: list[dict]) -> None:
    db.execute(GAME_PREDICTIONS_DDL)
    for column in (
        "absence_shift_per_100",
        "p_home_with_absences",
        "margin_with_absences",
        "home_points",
        "away_points",
        "total_sd",
    ):
        db.execute(f"ALTER TABLE game_predictions ADD COLUMN IF NOT EXISTS {column} DOUBLE")
    for row in upcoming:
        db.execute(
            "INSERT INTO game_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                row["season_code"],
                row["game_code"],
                row["p_home"],
                row["expected_margin"],
                row["margin_sd"],
                MODEL_USED,
                row["absence_shift"],
                row["p_home_with_absences"],
                row["margin_with_absences"],
                row["home_points"],
                row["away_points"],
                row["total_sd"],
            ],
        )


# For each game: the latest snapshot's home-win probability, bookmaker by
# bookmaker with that bookmaker's margin removed, then the median bookmaker.
MARKET_SQL = """
SELECT game_code, median((1 / home_price) / (1 / home_price + 1 / away_price)) AS p_market, count(*) AS bookmakers
FROM odds_snapshots
WHERE season_code = ? AND snapshot_utc = (SELECT max(snapshot_utc) FROM odds_snapshots)
GROUP BY game_code
"""
