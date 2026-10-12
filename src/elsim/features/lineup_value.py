"""Lineup-based player value: how a team's scoring margin moved while a player
was on the floor, holding the other nine players fixed (a ridge regression
over lineup stints, often called RAPM). Each side's head coach is in the
same regression, so what a team did beyond the sum of its players is
credited to its coach; coaches who move between clubs make the two
separable.

Values for a season are fitted only on stints of the seasons before it.
"""

from collections import defaultdict

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

PENALTY = 1e5  # ridge penalty; chosen by how well it predicted the next season's stints
SEASONS_USED = 3  # the fit uses up to the three previous seasons
SEASON_DECAY = 0.5  # each season further back counts half as much
COACH_PENALTY = 1e5  # ridge penalty for head coaches

# One row per stint from the home team's side, with the away five, only from
# games where every stint had five players on each side.
STINTS_SQL = """
SELECT s.season_code, s.player_ids, s.end_second - s.start_second AS seconds,
       s.points_for - s.points_against AS margin, o.player_ids AS opponent_ids,
       g.tipoff_utc, g.home_code, g.away_code
FROM lineup_stints AS s
JOIN games AS g USING (season_code, game_code)
JOIN game_checks AS c USING (season_code, game_code)
JOIN lineup_stints AS o ON o.season_code = s.season_code AND o.game_code = s.game_code
                       AND o.stint_number = s.stint_number AND o.team_code <> s.team_code
WHERE s.team_code = g.home_code AND c.five_check_passed AND s.end_second > s.start_second
"""


def coach_lookup(db):
    """Return a function (season, team, time) -> the head coach's id
    registered at that time, or None. If registrations overlap, the latest
    one counts."""
    spells = defaultdict(list)
    for season, team, coach, start, end in db.execute(
        "SELECT season_code, team_code, player_id, start_date, end_date FROM people WHERE type = 'E'"
    ).fetchall():
        spells[(season, team)].append((start, end, coach))

    def coach_at(season, team, when):
        current = [s for s in spells[(season, team)] if s[0] <= when <= s[1]]
        return max(current)[2] if current else None

    return coach_at


def load_stints(db) -> list[tuple]:
    """Stints as (season, home five, seconds, home margin, away five, home
    coach, away coach)."""
    coach_at = coach_lookup(db)
    return [
        (s, own, sec, margin, opp, coach_at(s, home, tipoff), coach_at(s, away, tipoff))
        for s, own, sec, margin, opp, tipoff, home, away in db.execute(STINTS_SQL).fetchall()
    ]


def fit_values(stints: list[tuple], seasons: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    """Return (player values, coach values), in points of margin per 40
    minutes above average, from the stints of the given seasons (oldest
    first). A player's value is per player on the floor; a coach's is for
    the whole team."""
    rows = [r for r in stints if r[0] in seasons]
    players = sorted({p for r in rows for p in r[1].split("|") + r[4].split("|")})
    coaches = sorted({c for r in rows for c in r[5:7] if c})
    column = {p: i for i, p in enumerate(players)}
    column.update({("coach", c): len(players) + i for i, c in enumerate(coaches)})
    i, j, v = [], [], []
    for k, (_, own, _, _, opponents, own_coach, opponent_coach) in enumerate(rows):
        for p in own.split("|"):
            i.append(k), j.append(column[p]), v.append(1.0)
        for p in opponents.split("|"):
            i.append(k), j.append(column[p]), v.append(-1.0)
        for coach, sign in ((own_coach, 1.0), (opponent_coach, -1.0)):
            if coach:
                i.append(k), j.append(column[("coach", coach)]), v.append(sign)
    X = sparse.csr_matrix((v, (i, j)), shape=(len(rows), len(column)))
    age = {s: len(seasons) - 1 - n for n, s in enumerate(seasons)}
    w = np.array([r[2] * SEASON_DECAY ** age[r[0]] for r in rows])
    y = np.array([r[3] / r[2] * 2400 for r in rows])
    home_edge = np.sum(w * y) / np.sum(w)
    penalty = np.r_[np.full(len(players), PENALTY), np.full(len(coaches), COACH_PENALTY)]
    A = X.T @ sparse.diags(w) @ X + sparse.diags(penalty)
    beta = spsolve(A.tocsc(), X.T @ (w * (y - home_edge))).tolist()
    return dict(zip(players, beta)), dict(zip(coaches, beta[len(players) :]))


def newcomer_value(values: dict[str, float], player_seasons: dict, earlier: list[str]) -> float:
    """Average value of the players in their first season in the data in the
    last earlier season; zero (average) when there is no older season to tell
    who was new."""
    if len(earlier) < 2:
        return 0.0
    last = earlier[-1]
    older = {p for (s, p) in player_seasons if s < last}
    new = [values[p] for (s, p) in player_seasons if s == last and p not in older and p in values]
    return float(np.mean(new)) if new else 0.0
