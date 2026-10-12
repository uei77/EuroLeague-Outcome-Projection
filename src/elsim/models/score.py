"""How close the expected scores came to the real ones on past games."""

import numpy as np

DEFAULT_PACE = 72.0  # possessions per 40 minutes, for a game with no pace yet


def _possessions(row: dict) -> float:
    paces = [p for p in (row.get("home_pace"), row.get("away_pace")) if p]
    return (sum(paces) / len(paces) if paces else DEFAULT_PACE) / 100.0


def _share_inside(errors: np.ndarray, spreads: np.ndarray, level: float) -> float:
    """Share of errors inside the central `level` interval of a normal spread."""
    z = {0.5: 0.6745, 0.8: 1.2816, 0.95: 1.96}[level]
    return float(np.mean(np.abs(errors) <= z * spreads))


def evaluate(rows: list[dict]) -> dict:
    """Mean absolute error of the expected home, away and total points and
    the margin, next to a forecast of every earlier season's average score,
    and how often the 80% intervals held the real margin and total.

    rows are walk-forward rows (backtest.predict_season) with the teams'
    season-to-date pace from the stage-two features."""
    poss = np.array([_possessions(r) for r in rows])
    home = np.array([r["s1_home_per_100"] for r in rows]) * poss
    away = np.array([r["s1_away_per_100"] for r in rows]) * poss
    real_home = np.array([r["home_score"] for r in rows], float)
    real_away = np.array([r["away_score"] for r in rows], float)
    seasons = sorted({r["season_code"] for r in rows})
    earlier = {s: [r for r in rows if r["season_code"] < s] or rows for s in seasons}
    base = {
        s: (np.mean([r["home_score"] for r in earlier[s]]), np.mean([r["away_score"] for r in earlier[s]]))
        for s in seasons
    }
    base_home = np.array([base[r["season_code"]][0] for r in rows])
    base_away = np.array([base[r["season_code"]][1] for r in rows])
    mae = lambda a, b: float(np.mean(np.abs(a - b)))
    return {
        "games": len(rows),
        "home": (mae(home, real_home), mae(base_home, real_home)),
        "away": (mae(away, real_away), mae(base_away, real_away)),
        "total": (mae(home + away, real_home + real_away), mae(base_home + base_away, real_home + real_away)),
        "margin": (mae(home - away, real_home - real_away), mae(base_home - base_away, real_home - real_away)),
        "margin_80": _share_inside(
            (real_home - real_away) - (home - away), np.array([r["s1_sd"] for r in rows]) * poss, 0.8
        ),
        "total_80": _share_inside(
            (real_home + real_away) - (home + away), np.array([r["s1_total_sd"] for r in rows]) * poss, 0.8
        ),
    }
