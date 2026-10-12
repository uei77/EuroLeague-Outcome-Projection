"""Why a forecast is what it is: the published forecast split into its parts,
and next to it what the factors left out of the forecast would add, with how
large they have been on past games.

Rest, travel, home and away form and the shot-profile matchup are in the
forecast with weights fitted on past seasons. The other factors are measured
on how far finished games ended from the published model's pre-game forecast
(points per 100 possessions); they did not improve forecasts when tried
(docs/TECHNICAL_NOTES.md, "Tried and not adopted"), so they are shown, never added.
"""

import numpy as np

from elsim.features.factors import FACTORS

FACTOR_EFFECTS_DDL = """CREATE TABLE IF NOT EXISTS factor_effects (
    run_id VARCHAR, factor VARCHAR, label VARCHAR, unit VARCHAR, effect_per_100 DOUBLE, se DOUBLE, games INTEGER,
    typical_difference DOUBLE)"""

GAME_EXPLANATIONS_DDL = """CREATE TABLE IF NOT EXISTS game_explanations (
    run_id VARCHAR, season_code VARCHAR, game_code INTEGER, part VARCHAR, label VARCHAR,
    home_minus_away DOUBLE, points DOUBLE, in_forecast BOOLEAN)"""

IN_FORECAST = {
    "ratings": "Team ratings (results so far, roster and head coach at the season start, later changes)",
    "home_edge": "Home edge (league-wide)",
    "missing": "Registered players currently not playing (missed the team's last three games)",
}
# Factors the rating model weighs itself, and the setting that holds the weight.
MODEL_TERMS = {"home_away": "form_effect", "rest": "rest_effect", "travel": "travel_effect", "style": "style_effect"}
LEFT_OUT = [name for name in FACTORS if name not in MODEL_TERMS]


def factor_effects(db, history: list[dict]) -> dict[str, tuple[float, float, int, float]]:
    """Return {factor: (effect per unit in points per 100 possessions, standard
    error, games, typical difference between two teams = standard deviation)} from a least-squares line of forecast error on all factors
    together, over the finished games in history."""
    inputs = {
        (r[0], r[1]): r[2:]
        for r in db.execute(f"SELECT season_code, game_code, {', '.join(LEFT_OUT)} FROM factor_inputs").fetchall()
    }
    used = [g for g in history if (g["season_code"], g["game_code"]) in inputs]
    X = np.array([[1.0, *inputs[(g["season_code"], g["game_code"])]] for g in used])
    y = np.array([g["actual_margin"] - g["forecast_margin"] for g in used])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    sigma2 = np.sum((y - X @ beta) ** 2) / (len(y) - X.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.pinv(X.T @ X)))
    spread = X[:, 1:].std(axis=0)
    return {
        name: (float(b), float(s), len(used), float(d)) for name, b, s, d in zip(LEFT_OUT, beta[1:], se[1:], spread)
    }


def explain(db, run_id: str, result: dict) -> dict[str, tuple[float, float, int]]:
    """Store, for every unplayed game of the run, its forecast split into
    parts (in_forecast true; they add up to the expected margin) and what each
    left-out factor would add (in_forecast false). Returns the factor effects."""
    games, params, _ = result["model"]
    state = result["state"]
    n = len(state.teams)
    edge = float(state.values[2 * n + 1])
    effects = factor_effects(db, result["history"])
    rosters = {
        (s, g, t): (a, r)
        for s, g, t, a, r in db.execute(
            "SELECT season_code, game_code, team_code, available_z, roster_z FROM roster_by_game"
        ).fetchall()
    }
    inputs = {
        (r[0], r[1]): dict(zip(FACTORS, r[2:]))
        for r in db.execute(f"SELECT season_code, game_code, {', '.join(FACTORS)} FROM factor_inputs").fetchall()
    }
    per_z = (params.roster_off - params.roster_def) * params.roster_move

    db.execute(FACTOR_EFFECTS_DDL)
    for name, (effect, se, count, spread) in effects.items():
        db.execute(
            "INSERT INTO factor_effects VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [run_id, name, *FACTORS[name], effect, se, count, spread],
        )
    db.execute(GAME_EXPLANATIONS_DDL)
    for row in result["upcoming"]:
        key = (row["season_code"], row["game_code"])
        home, away = (rosters.get(key + (t,), (0.0, 0.0)) for t in (row["home_code"], row["away_code"]))
        missing = (home[0] - home[1]) - (away[0] - away[1])
        parts = {"home_edge": (None, 0.0 if row["neutral"] else edge), "missing": (missing, per_z * missing)}
        terms = (
            {
                name: (inputs[key][name], getattr(params, setting) * inputs[key][name])
                for name, setting in MODEL_TERMS.items()
            }
            if key in inputs
            else {}
        )
        parts["ratings"] = (
            None,
            row["margin_per_100"] - parts["home_edge"][1] - parts["missing"][1] - sum(v for _, v in terms.values()),
        )
        lines = [(part, IN_FORECAST[part], value, per_100, True) for part, (value, per_100) in parts.items()]
        lines += [(name, FACTORS[name][0], value, per_100, True) for name, (value, per_100) in terms.items()]
        lines.append(
            (
                "absences",
                "Hand-entered absences (only in the forecast with absences)",
                None,
                row["absence_shift"],
                False,
            )
        )
        for name in LEFT_OUT:
            value = inputs.get(key, {}).get(name, 0.0)
            lines.append((name, FACTORS[name][0], value, effects[name][0] * value, False))
        for part, label, value, per_100, in_forecast in lines:
            db.execute(
                "INSERT INTO game_explanations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, *key, part, label, value, per_100 * row["possessions"], in_forecast],
            )
    return effects
