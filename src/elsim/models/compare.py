"""Compares two sets of out-of-sample forecasts of the same games.

Games in one round share news, schedules and refereeing, so they are not
independent; the uncertainty of a difference is found by resampling whole
rounds (block bootstrap), not single games.
"""

from math import log

import numpy as np


def log_loss(p: float, won: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -log(p if won else 1 - p)


def block(row: dict) -> tuple:
    """The resampling unit: one round of one season (each postseason phase
    counts as one round)."""
    return (row["season_code"], str(row["round"]) if row["phase"] == "RS" else row["phase"])


def compare(rows: list[dict], p_a: str, p_b: str, n_boot: int = 4000, seed: int = 20261011) -> dict:
    """Return how much forecast b changes log loss against forecast a (negative
    is better): mean difference, block-bootstrap standard error and 90%
    interval, the share of resamples in which b is better, and in how many
    seasons b is better."""
    diff = np.array([log_loss(r[p_b], r["home_won"]) - log_loss(r[p_a], r["home_won"]) for r in rows])
    keys = sorted({block(r) for r in rows})
    index = {k: i for i, k in enumerate(keys)}
    blocks = np.array([index[block(r)] for r in rows])
    sums, counts = np.bincount(blocks, diff, len(keys)), np.bincount(blocks, minlength=len(keys))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    boot = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    seasons = sorted({r["season_code"] for r in rows})
    by_season = {s: float(diff[[r["season_code"] == s for r in rows]].mean()) for s in seasons}
    return {
        "games": len(rows),
        "rounds": len(keys),
        "mean": float(diff.mean()),
        "se": float(boot.std()),
        "low": float(np.quantile(boot, 0.05)),
        "high": float(np.quantile(boot, 0.95)),
        "p_better": float((boot < 0).mean()),
        "seasons_better": sum(v < 0 for v in by_season.values()),
        "seasons": len(seasons),
        "by_season": by_season,
    }
