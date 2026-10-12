"""Checks the learned box-score value on hand-made player seasons."""

import numpy as np

from elsim.features.box_value import fit_box_value


def season(points, assists, seconds=60000):
    zero = dict.fromkeys(
        ["fga2", "fgm2", "fga3", "fgm3", "fta", "oreb", "dreb", "stl", "tov", "blk", "fouls", "fouls_drawn"], 10
    )
    return {
        **zero,
        "seconds": seconds,
        "points": points,
        "ast": assists,
        "usage_base": 400.0,
        "orb_base": 300.0,
        "drb_base": 300.0,
        "ast_base": 200.0,
    }


def test_a_stat_that_goes_with_lineup_value_gets_weight_and_later_seasons_are_ignored():
    rng = np.random.default_rng(0)
    players = {f"P{i}": rng.uniform(0, 20) for i in range(200)}
    seasons = {("S1", p): season(points=100 + 5 * a, assists=a) for p, a in players.items()}
    lineup = {p: 0.2 * a + rng.normal(scale=0.3) for p, a in players.items()}
    value = fit_box_value(lineup, seasons, ["S1"])
    assert value("P0", ["S1"]) is not None
    best, worst = max(players, key=players.get), min(players, key=players.get)
    assert value(best, ["S1"]) > value(worst, ["S1"])
    later = {**seasons, ("S2", best): season(points=0, assists=0)}
    assert fit_box_value(lineup, later, ["S1"])(best, ["S1"]) == value(best, ["S1"])
    assert value("unknown", ["S1"]) is None
