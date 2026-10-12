"""Runs the season simulation for the latest model run and stores the result."""

import json
import sys
from pathlib import Path

from elsim.models.predict import load_inputs
from elsim.models.state_space import Params, run_with_state
from elsim.simulate.monte_carlo import simulate

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

SIM_RESULTS_DDL = """CREATE TABLE IF NOT EXISTS sim_results (
    run_id VARCHAR, team_code VARCHAR, scenario VARCHAR, n_paths INTEGER,
    expected_wins DOUBLE, p_play_in DOUBLE, p_playoffs DOUBLE, p_final_four DOUBLE, p_title DOUBLE)"""


def load_format(settings: dict) -> dict:
    with open(Path("config") / settings["format_file"], "rb") as f:
        return tomllib.load(f)


def simulate_season(db, settings: dict) -> tuple[str, dict]:
    """Simulate the rest of the current season with the settings of the latest
    model run and store one row per team and scenario under that run id.

    Returns the run id and {scenario: result}. "baseline" ignores known
    absences. "with_absences" is added when the run has any: it shifts each
    game by how much the forecast changed when the absent players were left
    out of their team's available roster, and the play-in, playoffs and Final
    Four by what the absences still running at the season's last game are
    worth.
    """
    run_id, parameters, seed = db.execute(
        "SELECT run_id, parameters, seed FROM model_runs ORDER BY created_utc DESC LIMIT 1"
    ).fetchone()
    params = Params(**json.loads(parameters)["settings"])
    current = settings["current_season"]

    rows, games, season_start = load_inputs(db, current)
    _, state = run_with_state(games, params, season_start)

    played = db.execute(
        """SELECT home_code, away_code, home_score - away_score, home_standings_score - away_standings_score
           FROM games WHERE season_code = ? AND phase = 'RS' AND played""",
        [current],
    ).fetchall()
    remaining = db.execute(
        """SELECT g.home_code, g.away_code, coalesce(p.absence_shift_per_100, 0),
                  coalesce(f.rest, 0), coalesce(f.travel, 0), coalesce(f.home_away, 0), coalesce(f.style, 0)
           FROM games AS g
           LEFT JOIN game_predictions AS p
             ON p.run_id = ? AND p.season_code = g.season_code AND p.game_code = g.game_code
           LEFT JOIN factor_inputs AS f ON f.season_code = g.season_code AND f.game_code = g.game_code
           WHERE g.season_code = ? AND g.phase = 'RS' AND NOT g.played AND g.status <> 'Cancelled'
           ORDER BY g.tipoff_utc, g.game_code""",
        [run_id, current],
    ).fetchall()
    team_shift = dict(
        db.execute(
            "SELECT team_code, postseason_shift_per_100 FROM absence_shifts WHERE run_id = ?", [run_id]
        ).fetchall()
    )
    possessions = db.execute(
        "SELECT avg(possessions) FROM team_game_stats WHERE season_code = ?", [current]
    ).fetchone()[0]
    config = load_format(settings)

    fixtures = [g[:2] for g in remaining]
    # The rating model's own context terms for each game (rest, travel, home
    # and away form, shot-profile matchup), as in the game forecasts.
    context = [
        params.rest_effect * g[3] + params.travel_effect * g[4] + params.form_effect * g[5] + params.style_effect * g[6]
        for g in remaining
    ]
    absence_shift = [g[2] for g in remaining]
    results = {
        "baseline": simulate(state, params, played, fixtures, possessions, config, settings["n_paths"], seed, context)
    }
    if any(absence_shift) or any(team_shift.values()):
        results["with_absences"] = simulate(
            state,
            params,
            played,
            fixtures,
            possessions,
            config,
            settings["n_paths"],
            seed,
            [c + a for c, a in zip(context, absence_shift)],
            team_shift,
        )

    db.execute(SIM_RESULTS_DDL)
    db.execute("DELETE FROM sim_results WHERE run_id = ?", [run_id])
    for scenario, result in results.items():
        for i, team in enumerate(result["teams"]):
            db.execute(
                "INSERT INTO sim_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    team,
                    scenario,
                    result["n_paths"],
                    float(result["expected_wins"][i]),
                    float(result["play_in"][i]),
                    float(result["playoffs"][i]),
                    float(result["final_four"][i]),
                    float(result["title"][i]),
                ],
            )
    return run_id, results
