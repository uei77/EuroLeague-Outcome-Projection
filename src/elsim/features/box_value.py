"""A box-score player value learned from lineup values (a statistical
plus-minus).

For a season S, each player's lineup value (lineup_value.py, fitted on the
seasons before S) is regressed on his box-score rates and advanced
statistics over the same seasons. The learned weights then turn any
player's earlier box scores into a value on the lineup scale, which is far
less noisy for players with few lineup minutes. Everything uses only seasons
before S.

The settings below were set when the idea was first tested and not tuned,
except the ridge penalty, whose neighbours (25 and 100) gave the same
result (docs/TECHNICAL_NOTES.md, "Model tests").
"""

import numpy as np

RIDGE = 50.0  # penalty on each standardised weight
SEASON_DECAY = 0.5  # each season further back counts half as much
TS_PRIOR_ATTEMPTS = 20  # true shooting is pulled down as if by 20 attempts at 0.25 points each
TS_PRIOR = 0.25
MIN_WEIGHT_SECONDS = 300 * 60  # players with less (decayed) playing time are left out of the fit
NEWCOMER_PERCENTILE = 30  # a player with no EuroLeague box scores gets this percentile of known players

STATS = ["points", "fga2", "fga3", "fta", "oreb", "dreb", "ast", "stl", "tov", "blk", "fouls", "fouls_drawn"]
NAMES = STATS + ["ts", "usg", "orb_pct", "drb_pct", "ast_pct", "ts_x_usg"]

PLAYER_SEASONS_SQL = """
WITH team AS (
    SELECT season_code, game_code, team_code, sum(seconds) AS seconds, sum(fga2 + fga3) AS fga, sum(fta) AS fta,
           sum(tov) AS tov, sum(oreb) AS oreb, sum(dreb) AS dreb, sum(fgm2 + fgm3) AS fgm
    FROM box_player GROUP BY ALL
)
SELECT b.season_code, b.player_id, sum(b.seconds) AS seconds,
       sum(b.points) AS points, sum(b.fga2) AS fga2, sum(b.fgm2) AS fgm2, sum(b.fga3) AS fga3, sum(b.fgm3) AS fgm3,
       sum(b.fta) AS fta, sum(b.oreb) AS oreb, sum(b.dreb) AS dreb, sum(b.ast) AS ast, sum(b.stl) AS stl,
       sum(b.tov) AS tov, sum(b.blk) AS blk, sum(b.fouls) AS fouls, sum(b.fouls_drawn) AS fouls_drawn,
       sum(b.seconds * 5.0 / t.seconds * (t.fga + 0.44 * t.fta + t.tov)) AS usage_base,
       sum(b.seconds * 5.0 / t.seconds * (t.oreb + o.dreb)) AS orb_base,
       sum(b.seconds * 5.0 / t.seconds * (t.dreb + o.oreb)) AS drb_base,
       sum(b.seconds * 5.0 / t.seconds * t.fgm) AS ast_base
FROM box_player AS b
JOIN team AS t USING (season_code, game_code, team_code)
JOIN team AS o ON o.season_code = b.season_code AND o.game_code = b.game_code AND o.team_code <> b.team_code
WHERE b.seconds > 0
GROUP BY ALL
"""


def load_player_seasons(db) -> dict:
    cursor = db.execute(PLAYER_SEASONS_SQL)
    names = [c[0] for c in cursor.description]
    return {(r[0], r[1]): dict(zip(names, r)) for r in cursor.fetchall()}


def features(r: dict) -> np.ndarray:
    """Per-40-minute rates and advanced statistics of one player season."""
    per_40 = [r[k] / (r["seconds"] / 2400.0) for k in STATS]
    attempts = r["fga2"] + r["fga3"] + 0.44 * r["fta"]
    ts = (r["points"] + 2 * TS_PRIOR * TS_PRIOR_ATTEMPTS) / (2 * (attempts + TS_PRIOR_ATTEMPTS))
    usage = (attempts + r["tov"]) / max(r["usage_base"], 1)
    orb = r["oreb"] / max(r["orb_base"], 1)
    drb = r["dreb"] / max(r["drb_base"], 1)
    assists = r["ast"] / max(r["ast_base"] - (r["fgm2"] + r["fgm3"]), 1)
    return np.array(per_40 + [ts, usage, orb, drb, assists, ts * usage])


def history(player: str, seasons: list[str], player_seasons: dict) -> tuple[np.ndarray | None, float]:
    """A player's minutes-weighted features over the given seasons, each
    further back counting less, and the weight (decayed seconds) behind them."""
    total, weight, decay = None, 0.0, 1.0
    for season in reversed(seasons):
        r = player_seasons.get((season, player))
        if r:
            w = decay * r["seconds"]
            total = features(r) * w if total is None else total + features(r) * w
            weight += w
        decay *= SEASON_DECAY
    return (total / weight, weight) if weight else (None, 0.0)


def fit_box_value(lineup: dict[str, float], player_seasons: dict, fit_seasons: list[str]):
    """Learn weights turning box-score history into a lineup-scale value.
    Returns a function (player, earlier seasons) -> value or None."""
    rows = [(history(p, fit_seasons, player_seasons), value) for p, value in lineup.items()]
    rows = [(f, w, v) for (f, w), v in rows if f is not None and w > MIN_WEIGHT_SECONDS]
    X, w, y = (np.array([r[i] for r in rows]) for i in range(3))
    centre = np.average(X, axis=0, weights=w)
    spread = np.sqrt(np.average((X - centre) ** 2, axis=0, weights=w))
    spread[spread == 0] = 1.0  # a statistic every player shares carries no information
    A = np.column_stack([np.ones(len(X)), (X - centre) / spread])
    scale = w / w.mean()
    coef = np.linalg.solve(A.T @ (A * scale[:, None]) + np.diag([0.0] + [RIDGE] * X.shape[1]), A.T @ (y * scale))

    def value(player: str, earlier: list[str]) -> float | None:
        f, _ = history(player, earlier, player_seasons)
        return None if f is None else float(np.r_[1.0, (f - centre) / spread] @ coef)

    return value


def newcomer_box_value(values: list[float]) -> float:
    return float(np.percentile(values, NEWCOMER_PERCENTILE)) if values else 0.0
