"""Walk-forward backtest: every season is predicted with settings fitted only
on the seasons before it, and every game with data from before its tip-off."""

from math import log

import numpy as np
from scipy.optimize import minimize

from elsim.models.stage_two import fit_predict, load_features
from elsim.models.state_space import Game, Params, run

GAMES_SQL = """
SELECT g.season_code, g.game_code, g.round, g.phase, g.tipoff_utc, g.home_code, g.away_code,
       g.phase = 'FF' AS neutral,
       100.0 * h.points / h.possessions AS home_per_100,
       100.0 * a.points / a.possessions AS away_per_100,
       g.home_score > g.away_score AS home_won, g.home_score, g.away_score
FROM games AS g
JOIN team_game_stats AS h ON h.season_code = g.season_code AND h.game_code = g.game_code AND h.is_home
JOIN team_game_stats AS a ON a.season_code = g.season_code AND a.game_code = g.game_code AND NOT a.is_home
ORDER BY g.tipoff_utc, g.game_code
"""

# roster_move is fixed at 1 (a change of roster during the season counts as
# much as the same difference at the season start); fitting it overfitted.
START = Params(
    game_var=0.15, season_var=4.0, carry_over=0.6, noise_var=165.0, new_team_var=17.0, noise_corr=0.2, roster_move=1.0
)

# How each setting is mapped to an unconstrained number for the optimiser.
POSITIVE = ("game_var", "season_var", "noise_var", "new_team_var")
SHARE = ("carry_over",)
CORRELATION = ("noise_corr",)
BASE = POSITIVE + SHARE + CORRELATION
# The rating model without and with the roster component. The published one
# also weighs rest, travel, home and away form and the shot-profile matchup
# (owner's decision, 12 October 2026; see docs/TECHNICAL_NOTES.md, "Context terms").
CONTEXT = ("rest_effect", "travel_effect", "form_effect", "style_effect")
VARIANTS = {"p_rating": BASE, "p_roster": BASE + ("roster_off", "roster_def") + CONTEXT}
# Fitted context weights are halved before forecasting. At full weight they
# made forecasts worse than leaving them out (fitting picks up noise); at
# half weight they were as good as leaving them out (docs/TECHNICAL_NOTES.md, "Model tests").
CONTEXT_SHRINK = 0.5


def shrink_context(params: Params) -> Params:
    return params._replace(**{name: CONTEXT_SHRINK * getattr(params, name) for name in CONTEXT})


RATING_MODELS = ["p_constant", "p_rating", "p_roster"]
STAGE_TWO_MODELS = ["p_roster", "p_logistic", "p_lightgbm"]


def _encode(name: str, value: float) -> float:
    if name in POSITIVE:
        return log(value)
    if name in SHARE:
        value = min(max(value, 0.02), 0.98)
        return log(value / (1 - value))
    return float(np.arctanh(value)) if name in CORRELATION else value


def _decode(name: str, number: float) -> float:
    if name in POSITIVE:
        return float(np.exp(number))
    if name in SHARE:
        return float(1 / (1 + np.exp(-number)))
    return float(np.tanh(number)) if name in CORRELATION else float(number)


def fit(games: list[Game], season_start: dict, free: tuple[str, ...], start: Params = START) -> Params:
    """Return the settings that best predicted these games' points per 100
    possessions, each game predicted before it was used. Only the settings
    named in free are fitted; the rest stay as in start."""

    def build(theta: np.ndarray) -> Params:
        return start._replace(**{name: _decode(name, number) for name, number in zip(free, theta)})

    def loss(theta: np.ndarray) -> float:
        return -sum(p.log_likelihood for p in run(games, build(theta), season_start))

    theta = np.array([_encode(name, getattr(start, name)) for name in free])
    # The search starts with a step of 0.3 in every setting. The optimiser's
    # default step is proportional to the starting value, so a setting that
    # starts at zero would never be moved.
    simplex = np.vstack([theta, theta + 0.3 * np.eye(len(theta))])
    result = minimize(
        loss,
        theta,
        method="Nelder-Mead",
        options={"initial_simplex": simplex, "xatol": 1e-3, "fatol": 1e-3, "maxiter": 1500},
    )
    return build(result.x)


def log_loss(p: float, won: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -log(p if won else 1 - p)


def load_rosters(db, column: str = "available_z") -> tuple[dict, dict]:
    """Return each team's roster z-score at every game's tip-off, keyed by
    (season, game, team), and at its first game of the season, keyed by
    (season, team). column picks the players counted at each game:
    available_z (the published model) or known_absences_z (also without the
    hand-entered absences)."""
    by_game = {
        (s, g, t): z
        for s, g, t, z in db.execute(
            f"SELECT season_code, game_code, team_code, {column} FROM roster_by_game"
        ).fetchall()
    }
    season_start = dict(
        ((s, t), z) for s, t, z in db.execute("SELECT season_code, team_code, roster_z FROM season_start").fetchall()
    )
    return by_game, season_start


def load_context(db) -> dict:
    """Return (rest, travel, home and away form, shot-profile matchup) per
    (season, game), all from the home team's side; see features/factors.py."""
    return {
        (s, g): values
        for s, g, *values in db.execute(
            "SELECT season_code, game_code, rest, travel, home_away, style FROM factor_inputs"
        ).fetchall()
    }


def as_games(rows: list[dict], rosters: dict, context: dict | None = None) -> list[Game]:
    """Turn game rows into rating model input."""
    context = context or {}
    return [
        Game(
            r["season_code"],
            r["home_code"],
            r["away_code"],
            r["neutral"],
            r["home_per_100"],
            r["away_per_100"],
            rosters.get((r["season_code"], r["game_code"], r["home_code"])),
            rosters.get((r["season_code"], r["game_code"], r["away_code"])),
            *context.get((r["season_code"], r["game_code"]), (0.0, 0.0, 0.0, 0.0)),
        )
        for r in rows
    ]


def load_games(db) -> tuple[list[dict], list[Game], dict]:
    """Return game rows (with stage-two features), the same games as rating
    model input (with roster z-scores at tip-off), and each team's
    season-start roster z-score."""
    features = load_features(db)
    cursor = db.execute(GAMES_SQL)
    names = [c[0] for c in cursor.description]
    rows = [dict(zip(names, r)) for r in cursor.fetchall()]
    rows = [{**r, **features[(r["season_code"], r["game_code"])]} for r in rows]
    by_game, season_start = load_rosters(db)
    return rows, as_games(rows, by_game, load_context(db)), season_start


def predict_season(
    rows: list[dict], games: list[Game], season_start: dict, season: str, start: dict[str, Params] | None = None
) -> tuple[list[dict], dict[str, Params]]:
    """Predict one season with the rating model, its settings fitted only on
    earlier seasons.

    Returns one row per game of the season, with one probability per rating
    model variant, and the fitted settings. start may hold another season's
    fitted settings to begin the search from, which only saves time.
    """
    before = [i for i, r in enumerate(rows) if r["season_code"] < season]
    this = [i for i, r in enumerate(rows) if r["season_code"] == season]
    through = before + this
    past = [rows[i] for i in before if not rows[i]["neutral"]]
    home_rate = sum(r["home_won"] for r in past) / len(past)
    out = {i: {**rows[i], "p_constant": 0.5 if rows[i]["neutral"] else home_rate} for i in through}

    fitted = {}
    params = START
    for model, free in VARIANTS.items():
        # The richer model starts from the simpler one's fitted settings.
        params = fit([games[i] for i in before], season_start, free, start[model] if start else params)
        fitted[model] = params
        used = shrink_context(params) if set(CONTEXT) & set(free) else params
        for i, prediction in zip(through, run([games[i] for i in through], used, season_start)):
            out[i][model] = prediction.p_home
            out[i]["s1_margin"], out[i]["s1_sd"] = prediction.margin_per_100, prediction.margin_sd
            out[i]["s1_home_per_100"], out[i]["s1_away_per_100"] = prediction.home_per_100, prediction.away_per_100
            out[i]["s1_total_sd"] = prediction.total_sd

    return [out[i] for i in this], fitted


STAGE_TWO_MIN_SEASONS = 2


def add_stage_two(rows: list[dict], seed: int) -> None:
    """Add p_logistic and p_lightgbm to the rows of each season that has at
    least two earlier predicted seasons to learn from.

    Stage two is trained only on rating forecasts that were themselves out of
    sample. Training it on forecasts from seasons the rating model had been
    fitted on taught it to trust the rating model too much.
    """
    seasons = sorted({r["season_code"] for r in rows})
    for season in seasons[STAGE_TWO_MIN_SEASONS:]:
        train = [r for r in rows if r["season_code"] < season]
        test = [r for r in rows if r["season_code"] == season]
        p_logistic, p_gbm = fit_predict(train, test, seed)
        for row, a, b in zip(test, p_logistic, p_gbm):
            row["p_logistic"], row["p_lightgbm"] = float(a), float(b)


def walk_forward(db, first_test_season: str, seed: int) -> tuple[list[dict], dict]:
    """Return predictions for every season from first_test_season on, and the
    rating model's settings fitted for each season."""
    rows, games, season_start = load_games(db)
    out, fitted, start = [], {}, None
    for season in sorted({r["season_code"] for r in rows}):
        if season < first_test_season:
            continue
        season_rows, start = predict_season(rows, games, season_start, season, start)
        out += season_rows
        fitted[season] = start
        print(f"{season}: predicted {len(season_rows)} games", flush=True)
    add_stage_two(out, seed)
    return out, fitted


def summary(rows: list[dict], models: list[str]) -> list[tuple]:
    """Return (group, games, then log loss per model) for all games, the first
    ten rounds of the seasons taken together, and each season. Only games
    that every listed model predicted are counted, so the columns compare
    like with like."""
    rows = [r for r in rows if all(m in r for m in models)]
    groups = [("all", rows), ("rounds 1-10", [r for r in rows if r["phase"] == "RS" and r["round"] <= 10])]
    groups += [(s, [r for r in rows if r["season_code"] == s]) for s in sorted({r["season_code"] for r in rows})]
    return [
        (name, len(group), *(sum(log_loss(r[m], r["home_won"]) for r in group) / len(group) for m in models))
        for name, group in groups
    ]
