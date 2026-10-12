"""A tuned Elo rating, the strongest simple yardstick for the published model.

Each team has one number. The home side wins with probability
1 / (1 + 10^(-(home - away + home edge) / 400)); after the game both move by
K x (result - expected), larger for bigger wins. Between seasons every
rating is pulled part of the way back to the average. The four settings are
chosen by grid search on earlier seasons only.
"""

from itertools import product
from math import log

GRID = {
    "k": (3, 5, 7, 10, 15, 20, 30),
    "home": (40, 70, 100, 130, 160),
    "carry": (0.35, 0.5, 0.65, 0.8),
    "margin": (0.0, 1.0),
}


def run(rows: list[dict], k: float, home: float, carry: float, margin: float) -> list[float]:
    """Return the pre-game home-win probability of each row (rows in playing
    order, with season_code, home_code, away_code, neutral, home_won and the
    score margin in "margin" for played games)."""
    rating, season, out = {}, None, []
    for r in rows:
        if r["season_code"] != season:
            season = r["season_code"]
            rating = {t: 1500 + carry * (v - 1500) for t, v in rating.items()}
        h, a = rating.get(r["home_code"], 1500.0), rating.get(r["away_code"], 1500.0)
        edge = 0.0 if r["neutral"] else home
        p = 1 / (1 + 10 ** (-(h - a + edge) / 400))
        out.append(p)
        size = (1 + abs(r["margin"])) ** 0.5 if margin else 1.0  # bigger wins move ratings more
        change = k * size * (float(r["home_won"]) - p)
        rating[r["home_code"]], rating[r["away_code"]] = h + change, a - change
    return out


def _loss(p: float, won: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -log(p if won else 1 - p)


def walk_forward(rows: list[dict], first_test_season: str) -> tuple[list[float | None], dict]:
    """Return, per row, the Elo forecast with settings chosen on the seasons
    before the row's season (None before first_test_season), and the chosen
    settings per season."""
    out, chosen = [None] * len(rows), {}
    for season in sorted({r["season_code"] for r in rows}):
        if season < first_test_season:
            continue
        before = [i for i, r in enumerate(rows) if r["season_code"] < season]
        best = min(
            product(*GRID.values()),
            key=lambda s: sum(
                _loss(p, rows[i]["home_won"]) for i, p in zip(before, run([rows[i] for i in before], *s))
            ),
        )
        chosen[season] = dict(zip(GRID, best))
        through = [i for i, r in enumerate(rows) if r["season_code"] <= season]
        for i, p in zip(through, run([rows[i] for i in through], *best)):
            if rows[i]["season_code"] == season:
                out[i] = p
    return out, chosen
