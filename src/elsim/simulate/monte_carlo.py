"""Simulates the rest of the season many times and counts how each team ends up.

Each path first draws every team's strength from what the rating model
currently believes, uncertainty included, and keeps it for the whole path.
Then the remaining regular-season games are played, the table is ordered with
the tie-break rules, and the play-in, playoffs and Final Four follow.
"""

from math import sqrt

import numpy as np

from elsim.models.state_space import Params, State
from elsim.simulate.postseason import Strengths, knockout, play_in
from elsim.simulate.table import rank, tallies

CHUNK = 10_000  # paths simulated at a time, to keep memory small


def simulate(
    state: State,
    params: Params,
    played: list[tuple],
    remaining: list[tuple],
    possessions: float,
    config: dict,
    n_paths: int,
    seed: int,
    game_shift: list[float] | None = None,
    team_shift: dict[str, float] | None = None,
) -> dict:
    """Return per-team probabilities and counts.

    played      finished regular-season games: (home, away, final margin, standings margin)
    remaining   unplayed regular-season games: (home, away)
    possessions average possessions of a team in a game, to turn points per 100 into points
    game_shift  schedule context and known absences: change in each remaining game's margin, home
                minus away, in points per 100 possessions
    team_shift  known absences lasting into the postseason: change in a
                team's strength there, in points per 100 possessions
    """
    rng = np.random.default_rng(seed)
    teams = sorted({t for g in played + remaining for t in g[:2]})
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    model_index = {team: i for i, team in enumerate(state.teams)}
    m = len(state.teams)
    columns = [model_index[t] for t in teams]

    base = tallies(n, [(index[h], index[a], margin, standings) for h, a, margin, standings in played])
    home = np.array([index[h] for h, _ in remaining], dtype=int)
    away = np.array([index[a] for _, a in remaining], dtype=int)
    noise_sd = sqrt(2 * params.noise_var * (1 - params.noise_corr))
    direct = config["direct_playoff_places"]
    shift = np.array(game_shift if game_shift is not None else [0.0] * len(remaining))
    postseason_shift = np.array([(team_shift or {}).get(team, 0.0) for team in teams])

    counts = {key: np.zeros(n, dtype=int) for key in ("play_in", "playoffs", "final_four", "title")}
    n_games = len(played) + len(remaining)
    place_counts = np.zeros((n, n), dtype=int)  # [team, final regular-season place]
    win_counts = np.zeros((n, n_games + 1), dtype=int)  # [team, regular-season wins]
    win_total = np.zeros(n)
    random_ties = 0
    done = 0
    while done < n_paths:
        size = min(CHUNK, n_paths - done)
        draws = rng.multivariate_normal(state.values, state.covariance, size=size, method="eigh")
        net = draws[:, columns] - draws[:, [m + c for c in columns]]
        edge = draws[:, 2 * m + 1]
        strengths = Strengths(net, edge, noise_sd, rng)

        # Remaining regular-season games, all paths at once. The margin in
        # points decides the winner; rounded, it is the score difference for
        # the table, and a margin that rounds to zero stands for a game that
        # went to overtime (level in the standings score).
        margin = (
            (
                net[:, home]
                - net[:, away]
                + edge[:, None]
                + shift
                + noise_sd * rng.standard_normal((size, len(remaining)))
            )
            * possessions
            / 100.0
        )
        home_won = margin > 0
        table_margin = np.rint(margin).astype(int)

        wins = np.tile(np.array(base[0]), (size, 1))
        h2h_wins = np.tile(np.array(base[1]), (size, 1, 1))
        h2h_diff = np.tile(np.array(base[2]), (size, 1, 1))
        total_diff = np.tile(np.array(base[3]), (size, 1))
        for g in range(len(remaining)):
            h, a = home[g], away[g]
            won, diff = home_won[:, g], table_margin[:, g]
            wins[:, h] += won
            wins[:, a] += ~won
            h2h_wins[:, h, a] += won
            h2h_wins[:, a, h] += ~won
            total_diff[:, h] += diff
            total_diff[:, a] -= diff
            h2h_diff[:, h, a] += diff
            h2h_diff[:, a, h] -= diff

        order = np.empty((size, n), dtype=int)
        unresolved = []
        for p in range(size):
            order[p] = rank(wins[p].tolist(), h2h_wins[p], h2h_diff[p], total_diff[p], rng, unresolved)
        random_ties += len(unresolved)

        strengths.net = net + postseason_shift
        seed_seven, seed_eight = play_in(order[:, direct : direct + 4], strengths)
        top_eight = np.column_stack([order[:, :direct], seed_seven, seed_eight])
        final_four, champion = knockout(top_eight, strengths, config)

        for key, reached in (
            ("play_in", order[:, direct : direct + 4]),
            ("playoffs", top_eight),
            ("final_four", final_four),
            ("title", champion[:, None]),
        ):
            counts[key] += np.bincount(reached.ravel(), minlength=n)
        win_total += wins.sum(axis=0)
        for place in range(n):
            place_counts[:, place] += np.bincount(order[:, place], minlength=n)
        for team in range(n):
            win_counts[team] += np.bincount(wins[:, team], minlength=n_games + 1)
        done += size

    return {
        "teams": teams,
        "n_paths": n_paths,
        "random_ties": random_ties,
        "expected_wins": win_total / n_paths,
        "place": place_counts / n_paths,
        "wins": win_counts / n_paths,
        **{key: value / n_paths for key, value in counts.items()},
    }
