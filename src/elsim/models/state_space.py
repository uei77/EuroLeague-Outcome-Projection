"""Stage one: a state-space model of team offence and defence.

Each team has an offence and a defence value, in points per 100 possessions
relative to the league. A game is two observations:

    home points per 100 = league + home offence + away defence + home edge / 2
    away points per 100 = league + away offence + home defence - home edge / 2

(defence is points allowed above the league, so lower is better). Known
schedule context (rest days, travel) can add a fixed amount to the home
margin, split between the two. Each value
is held as an estimate with an uncertainty and updated game by game with a
Kalman filter. Every prediction is made before the game's result is used.
"""

from math import erf, log, pi, sqrt
from typing import NamedTuple

import numpy as np


class Params(NamedTuple):
    game_var: float  # how much a team's values can drift from one game to the next
    season_var: float  # extra uncertainty added to every team between seasons
    carry_over: float  # share of a team's values kept from one season to the next (0 to 1)
    noise_var: float  # game-to-game randomness of points per 100 possessions
    new_team_var: float  # uncertainty about a team seen for the first time
    noise_corr: float  # how far the two teams' randomness in one game moves together (-1 to 1)
    roster_off: float = 0.0  # offence points per 100 for a roster one standard deviation above average
    roster_def: float = 0.0  # the same for defence (negative means stronger rosters concede less)
    roster_move: float = 0.0  # share of the roster effect applied when the roster changes during a season
    rest_effect: float = 0.0  # home margin per 100 possessions per extra day of rest over the opponent
    travel_effect: float = 0.0  # home margin per 100 possessions per 1,000 km more travelled by the away team
    form_effect: float = 0.0  # share of the two teams' home and away form (features/factors.py) added to the margin
    style_effect: float = 0.0  # share of the shot-profile matchup added to the margin
    venue_effect: float = 0.0  # share of the two teams' long-run home and away splits added to the margin
    abroad_effect: float = 0.0  # home margin per 100 possessions when the home team plays far from its home city


# League level and home edge move slowly; these are fixed, not fitted.
LEAGUE_START, LEAGUE_START_VAR, LEAGUE_GAME_VAR, LEAGUE_SEASON_VAR = 112.0, 100.0, 0.02, 4.0
EDGE_START, EDGE_START_VAR, EDGE_GAME_VAR, EDGE_SEASON_VAR = 6.0, 25.0, 0.005, 1.0


class Game(NamedTuple):
    season: str
    home: str
    away: str
    neutral: bool
    home_per_100: float | None  # None for a game not yet played
    away_per_100: float | None
    home_roster: float | None = None  # home roster z-score at tip-off, None if unknown
    away_roster: float | None = None
    rest_diff: float = 0.0  # home rest days minus away rest days
    travel_diff: float = 0.0  # away travel minus home travel, in 1,000 km
    form_diff: float = 0.0  # home team's home form plus away team's away form, points per 100
    style_diff: float = 0.0  # shot-profile matchup, home minus away, points per 100 shots
    venue_diff: float = 0.0  # home team's long-run home split plus away team's, points per 100
    abroad: float = 0.0  # 1 when the home team plays its home game far from its home city


class State(NamedTuple):
    """What the model believes after the games it has seen. values holds, in
    order, every team's offence, every team's defence, the league level and
    the home edge; covariance is the uncertainty about them."""

    teams: list[str]
    values: np.ndarray
    covariance: np.ndarray


class Prediction(NamedTuple):
    home_per_100: float
    away_per_100: float
    margin_per_100: float
    margin_sd: float
    p_home: float
    log_likelihood: float | None  # of the observed result, None if not played
    total_sd: float = 0.0  # spread of the two teams' combined points per 100


def run(
    games: list[Game], params: Params, season_start: dict[tuple[str, str], float] | None = None
) -> list[Prediction]:
    """Return the pre-game prediction for each game. See run_with_state."""
    return run_with_state(games, params, season_start)[0]


def run_with_state(
    games: list[Game], params: Params, season_start: dict[tuple[str, str], float] | None = None
) -> tuple[list[Prediction], State]:
    """Filter through games in the order given (must be chronological) and
    return the pre-game prediction for each, and the state after the last
    played game.

    season_start maps (season, team) to the team's roster z-score. At the
    start of a season a team's values become
        carry-over x last season's values + roster effect x roster z-score.
    A team without an entry keeps the plain carry-over; a new team without an
    entry starts at the league average.

    When a game carries a team's roster z-score at tip-off and it differs
    from the last one applied (a signing or a departure), the team's values
    move by roster_move x roster effect x the change.
    """
    season_start = season_start or {}
    teams = sorted({g.home for g in games} | {g.away for g in games})
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    league, edge = 2 * n, 2 * n + 1
    x = np.zeros(2 * n + 2)
    x[league], x[edge] = LEAGUE_START, EDGE_START
    P = np.zeros((2 * n + 2, 2 * n + 2))
    P[league, league], P[edge, edge] = LEAGUE_START_VAR, EDGE_START_VAR
    seen: set[str] = set()
    season = None
    R = params.noise_var * np.array([[1.0, params.noise_corr], [params.noise_corr, 1.0]])
    predictions = []
    applied: dict[str, float] = {}

    for game in games:
        if game.season != season:
            first_season = season is None
            season = game.season
            scale = np.ones(2 * n + 2)
            for team, i in index.items():
                z = season_start.get((season, team), 0.0)
                applied[team] = z
                if team in seen:
                    scale[i] = scale[n + i] = params.carry_over
                    x[i], x[n + i] = params.carry_over * x[i], params.carry_over * x[n + i]
                x[i] += params.roster_off * z
                x[n + i] += params.roster_def * z
            if not first_season:
                P = P * np.outer(scale, scale)
                for team in seen:
                    for k in (index[team], n + index[team]):
                        P[k, k] += params.season_var
                P[league, league] += LEAGUE_SEASON_VAR
                P[edge, edge] += EDGE_SEASON_VAR

        for team, z in ((game.home, game.home_roster), (game.away, game.away_roster)):
            if z is not None and params.roster_move and z != applied[team]:
                change = params.roster_move * (z - applied[team])
                x[index[team]] += params.roster_off * change
                x[n + index[team]] += params.roster_def * change
                applied[team] = z

        # Drift is added on a copy, so predicting a game that has not been
        # played leaves the model exactly as it was.
        h, a = index[game.home], index[game.away]
        played = game.home_per_100 is not None
        Q = P.copy()
        for team, i in ((game.home, h), (game.away, a)):
            if team not in seen:
                Q[i, i] = Q[n + i, n + i] = params.new_team_var
            else:
                Q[i, i] += params.game_var
                Q[n + i, n + i] += params.game_var
        Q[league, league] += LEAGUE_GAME_VAR
        Q[edge, edge] += EDGE_GAME_VAR

        H = np.zeros((2, 2 * n + 2))
        H[0, [h, n + a, league]] = 1.0
        H[1, [a, n + h, league]] = 1.0
        if not game.neutral:
            H[0, edge], H[1, edge] = 0.5, -0.5

        expected = H @ x
        context = (
            params.rest_effect * game.rest_diff
            + params.travel_effect * game.travel_diff
            + params.form_effect * game.form_diff
            + params.style_effect * game.style_diff
            + params.venue_effect * game.venue_diff
            + params.abroad_effect * game.abroad
        )
        expected = expected + np.array([context / 2, -context / 2])
        S = H @ Q @ H.T + R
        margin = expected[0] - expected[1]
        margin_sd = sqrt(S[0, 0] + S[1, 1] - 2 * S[0, 1])
        p_home = 0.5 * (1 + erf(margin / (margin_sd * sqrt(2))))

        log_likelihood = None
        if played:
            residual = np.array([game.home_per_100, game.away_per_100]) - expected
            S_inv = np.linalg.inv(S)
            log_likelihood = -0.5 * (residual @ S_inv @ residual + log(np.linalg.det(S)) + 2 * log(2 * pi))
            K = Q @ H.T @ S_inv
            x = x + K @ residual
            P = Q - K @ S @ K.T
            seen.update((game.home, game.away))

        total_sd = sqrt(S[0, 0] + S[1, 1] + 2 * S[0, 1])
        predictions.append(Prediction(expected[0], expected[1], margin, margin_sd, p_home, log_likelihood, total_sd))
    return predictions, State(teams, x, P)
