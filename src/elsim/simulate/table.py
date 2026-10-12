"""Orders teams in the regular-season table, including the tie-break rules.

Rules as published for 2026-27 (see config/format_2026.toml for the wording):
teams level on wins are separated by
  1. record in the games between the tied teams,
  2. score difference in the games between the tied teams,
  3. score difference over the whole regular season,
  4. points scored over the whole regular season,
  5. sum of quotients of points for and against in each game.
When a step separates only some of the tied teams, the process starts again
from step 1 for each group still tied. Points scored in overtime do not count
in any of these.

Steps 4 and 5 are not implemented: the simulator draws score differences, not
scores. A tie that survives step 3 is broken at random, and counted.
"""


def rank(wins, h2h_wins, h2h_diff, total_diff, rng, unresolved: list | None = None) -> list[int]:
    """Return team indices from first to last place.

    wins[i]          regular-season wins of team i
    h2h_wins[i][j]   wins of team i over team j
    h2h_diff[i][j]   score difference of team i in its games against team j
    total_diff[i]    score difference of team i over the whole season
    unresolved       if given, every tie broken at random is appended to it
    """

    def separate(group: list[int]) -> list[int]:
        if len(group) == 1:
            return group
        for key in (
            lambda t: sum(h2h_wins[t][u] for u in group if u != t),
            lambda t: sum(h2h_diff[t][u] for u in group if u != t),
            lambda t: total_diff[t],
        ):
            values = {t: key(t) for t in group}
            if len(set(values.values())) > 1:
                ordered = []
                for value in sorted(set(values.values()), reverse=True):
                    ordered += separate([t for t in group if values[t] == value])
                return ordered
        if unresolved is not None:
            unresolved.append(list(group))
        return [group[i] for i in rng.permutation(len(group))]

    order = []
    for value in sorted(set(wins), reverse=True):
        order += separate([t for t in range(len(wins)) if wins[t] == value])
    return order


def tallies(n_teams: int, games: list[tuple[int, int, int, int]]):
    """Return (wins, h2h_wins, h2h_diff, total_diff) for finished games given
    as (home index, away index, home margin in final score, home margin in
    standings score)."""
    wins = [0] * n_teams
    total_diff = [0] * n_teams
    h2h_wins = [[0] * n_teams for _ in range(n_teams)]
    h2h_diff = [[0] * n_teams for _ in range(n_teams)]
    for home, away, margin, standings_margin in games:
        winner, loser = (home, away) if margin > 0 else (away, home)
        wins[winner] += 1
        h2h_wins[winner][loser] += 1
        total_diff[home] += standings_margin
        total_diff[away] -= standings_margin
        h2h_diff[home][away] += standings_margin
        h2h_diff[away][home] -= standings_margin
    return wins, h2h_wins, h2h_diff, total_diff
