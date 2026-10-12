"""Checks the season simulator on past seasons.

For each past season and each checkpoint (after round 5, 15 and 25), the rest
of the regular season is simulated from what the rating model believed at
that point, with settings fitted only on earlier seasons. The simulated
chances and win totals are then compared with how the season really ended.

Only the regular season is judged (final place and wins), because that is the
same in every season; the play-in did not exist before 2023-24.
"""

import numpy as np

from elsim.models.state_space import run_with_state
from elsim.simulate.monte_carlo import simulate
from elsim.simulate.table import rank, tallies

CHECKPOINTS = [5, 15, 25]
# 2019-20 was stopped early and 2021-22 had three clubs' results annulled,
# so neither has a final table this code can reproduce.
SKIPPED_SEASONS = {"E2019", "E2021"}
INTERVALS = [0.5, 0.8, 0.95]


def season_checkpoint(
    rows, games, season_start, params, season: str, after_round: int, config: dict, n_paths: int, seed: int
) -> list[dict]:
    """Simulate one season from one checkpoint. Returns one record per team:
    simulated chances and win distribution, and what really happened."""
    known = [
        i
        for i, r in enumerate(rows)
        if r["played"]
        and (
            r["season_code"] < season
            or (r["season_code"] == season and r["phase"] == "RS" and r["round"] <= after_round)
        )
    ]
    _, state = run_with_state([games[i] for i in known], params, season_start)

    regular = [r for r in rows if r["season_code"] == season and r["phase"] == "RS" and r["played"]]
    as_result = lambda r: (
        r["home_code"],
        r["away_code"],
        r["home_score"] - r["away_score"],
        r["home_standings_score"] - r["away_standings_score"],
    )
    played = [as_result(r) for r in regular if r["round"] <= after_round]
    remaining = [(r["home_code"], r["away_code"]) for r in regular if r["round"] > after_round]
    possessions = float(np.mean([r["pace"] for r in regular if r["round"] <= after_round and r["pace"]]))

    result = simulate(state, params, played, remaining, possessions, config, n_paths, seed)
    teams = result["teams"]
    index = {t: i for i, t in enumerate(teams)}
    final = [as_result(r) for r in regular]
    wins, h2h_wins, h2h_diff, total_diff = tallies(len(teams), [(index[h], index[a], m, s) for h, a, m, s in final])
    order = rank(wins, h2h_wins, h2h_diff, total_diff, np.random.default_rng(seed))
    place = {team: order.index(i) + 1 for i, team in enumerate(teams)}

    records = []
    for i, team in enumerate(teams):
        cumulative = np.cumsum(result["wins"][i])
        quantile = lambda q: int(np.searchsorted(cumulative, q))
        records.append(
            {
                "season": season,
                "after_round": after_round,
                "team": team,
                "p_top4": float(result["place"][i, :4].sum()),
                "p_top8": float(result["place"][i, :8].sum()),
                "top4": place[team] <= 4,
                "top8": place[team] <= 8,
                "expected_wins": float(result["expected_wins"][i]),
                "wins": wins[i],
                **{
                    f"inside_{int(level * 100)}": quantile((1 - level) / 2) <= wins[i] <= quantile((1 + level) / 2)
                    for level in INTERVALS
                },
            }
        )
    return records


def summarise(records: list[dict]) -> list[dict]:
    """One line per checkpoint and one for all: is a stated chance of
    finishing in the top eight honest, and do the simulated win totals leave
    enough room for what really happened?"""
    lines = []
    for name, group in [(str(c), [r for r in records if r["after_round"] == c]) for c in CHECKPOINTS] + [
        ("all", records)
    ]:
        if not group:
            continue
        n = len(group)
        base8 = sum(r["top8"] for r in group) / n
        lines.append(
            {
                "after_round": name,
                "team_seasons": n,
                "brier_top8": sum((r["p_top8"] - r["top8"]) ** 2 for r in group) / n,
                "brier_top8_no_skill": base8 * (1 - base8),
                "brier_top4": sum((r["p_top4"] - r["top4"]) ** 2 for r in group) / n,
                "wins_error": sum(abs(r["expected_wins"] - r["wins"]) for r in group) / n,
                **{
                    f"inside_{int(level * 100)}": sum(r[f"inside_{int(level * 100)}"] for r in group) / n
                    for level in INTERVALS
                },
            }
        )
    return lines


def calibration(records: list[dict], key: str = "top8") -> list[tuple]:
    """Return (low, high, team-seasons, mean stated chance, share that happened)."""
    edges = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0001]
    out = []
    for low, high in zip(edges, edges[1:]):
        group = [r for r in records if low <= r[f"p_{key}"] < high]
        if group:
            out.append(
                (
                    low,
                    min(high, 1.0),
                    len(group),
                    sum(r[f"p_{key}"] for r in group) / len(group),
                    sum(r[key] for r in group) / len(group),
                )
            )
    return out
