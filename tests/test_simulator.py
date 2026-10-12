"""Checks the season simulator on the real 2025-26 season."""

import csv
import sys
from pathlib import Path

import numpy as np

from elsim.models.state_space import Game, Params, run_with_state
from elsim.simulate.monte_carlo import simulate
from elsim.simulate.table import rank, tallies

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).parent.parent
PARAMS = Params(
    game_var=0.16,
    season_var=3.8,
    carry_over=0.44,
    noise_var=165.0,
    new_team_var=16.0,
    noise_corr=0.2,
    roster_off=1.2,
    roster_def=-0.4,
)
# The real final order of the 2025-26 regular season, as shown by the play-in
# and playoff pairings that followed it.
REAL_TOP_TEN = ["OLY", "PAM", "MAD", "ULK", "ZAL", "HTA", "PAN", "MCO", "BAR", "RED"]


def read(name: str) -> list[dict]:
    with open(ROOT / "tests" / "fixtures" / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def regular_season() -> list[tuple]:
    return [
        (
            g["home_code"],
            g["away_code"],
            int(g["home_score"]) - int(g["away_score"]),
            int(g["home_standings_score"]) - int(g["away_standings_score"]),
        )
        for g in sorted(read("games_E2025.csv"), key=lambda g: (g["tipoff_utc"], int(g["game_code"])))
        if g["phase"] == "RS" and g["played"] == "true"
    ]


def state_after(n_games: int):
    """The rating model's state after the first n_games regular-season games."""
    stats = {(r["game_code"], r["team_code"]): r for r in read("team_game_stats_E2025.csv")}
    per_100 = lambda r: 100.0 * int(r["points"]) / int(r["possessions"])
    games = []
    for g in sorted(read("games_E2025.csv"), key=lambda g: (g["tipoff_utc"], int(g["game_code"]))):
        if g["phase"] == "RS" and g["played"] == "true":
            home, away = stats[(g["game_code"], g["home_code"])], stats[(g["game_code"], g["away_code"])]
            games.append(Game("E2025", g["home_code"], g["away_code"], False, per_100(home), per_100(away)))
    return run_with_state(games[:n_games], PARAMS)[1]


def config() -> dict:
    with open(ROOT / "config" / "format_2026.toml", "rb") as f:
        return tomllib.load(f)


def result(n_played: int, n_paths: int, seed: int) -> dict:
    games = regular_season()
    return simulate(
        state_after(n_played),
        PARAMS,
        games[:n_played],
        [g[:2] for g in games[n_played:]],
        72.0,
        config(),
        n_paths,
        seed,
    )


def test_table_rules_reproduce_the_real_final_order():
    games = regular_season()
    teams = sorted({t for g in games for t in g[:2]})
    index = {t: i for i, t in enumerate(teams)}
    unresolved = []
    order = rank(
        *tallies(len(teams), [(index[h], index[a], m, s) for h, a, m, s in games]), np.random.default_rng(0), unresolved
    )
    assert [teams[i] for i in order[:10]] == REAL_TOP_TEN
    assert unresolved == []


def test_probabilities_sum_to_the_number_of_places():
    r = result(n_played=100, n_paths=2000, seed=1)
    assert abs(r["title"].sum() - 1) < 1e-9
    assert abs(r["final_four"].sum() - 4) < 1e-9
    assert abs(r["playoffs"].sum() - 8) < 1e-9
    assert abs(r["play_in"].sum() - 4) < 1e-9


def test_same_seed_gives_the_same_result_and_another_seed_does_not():
    a, b, c = result(100, 2000, seed=7), result(100, 2000, seed=7), result(100, 2000, seed=8)
    for key in ("play_in", "playoffs", "final_four", "title", "expected_wins"):
        assert (a[key] == b[key]).all()
    assert (a["title"] != c["title"]).any()


def test_decided_places_show_as_certain_once_the_regular_season_is_over():
    r = result(n_played=len(regular_season()), n_paths=500, seed=1)
    place = {team: i for i, team in enumerate(r["teams"])}
    for team in REAL_TOP_TEN[:6]:  # straight into the playoffs
        assert r["playoffs"][place[team]] == 1.0 and r["play_in"][place[team]] == 0.0
    for team in REAL_TOP_TEN[6:]:  # in the play-in for certain, playoffs still open
        assert r["play_in"][place[team]] == 1.0 and 0.0 < r["playoffs"][place[team]] < 1.0
    for team in set(r["teams"]) - set(REAL_TOP_TEN):  # out for certain
        assert r["playoffs"][place[team]] == 0.0 and r["title"][place[team]] == 0.0


def test_place_and_win_distributions_are_complete():
    r = result(n_played=100, n_paths=2000, seed=1)
    assert abs(r["place"].sum(axis=1) - 1).max() < 1e-9  # every team ends somewhere
    assert abs(r["place"].sum(axis=0) - 1).max() < 1e-9  # every place is taken by someone
    assert abs(r["wins"].sum(axis=1) - 1).max() < 1e-9
    expected = (r["wins"] * range(r["wins"].shape[1])).sum(axis=1)
    assert abs(expected - r["expected_wins"]).max() < 1e-9


def test_simulator_backtest_summary_counts_what_happened():
    from elsim.simulate.backtest import calibration, summarise

    records = [
        {
            "after_round": 5,
            "p_top8": 0.9,
            "top8": True,
            "p_top4": 0.2,
            "top4": False,
            "expected_wins": 20.0,
            "wins": 22,
            "inside_50": False,
            "inside_80": True,
            "inside_95": True,
        },
        {
            "after_round": 5,
            "p_top8": 0.1,
            "top8": False,
            "p_top4": 0.0,
            "top4": False,
            "expected_wins": 10.0,
            "wins": 10,
            "inside_50": True,
            "inside_80": True,
            "inside_95": True,
        },
    ]
    line = summarise(records)[0]
    assert (line["team_seasons"], line["wins_error"], line["inside_50"], line["inside_80"]) == (2, 1.0, 0.5, 1.0)
    assert abs(line["brier_top8"] - 0.01) < 1e-12 and line["brier_top8_no_skill"] == 0.25
    assert [(n, happened) for _, _, n, _, happened in calibration(records)] == [(1, 0.0), (1, 1.0)]
