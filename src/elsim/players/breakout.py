"""Players to Watch: who is expected to produce most in a round, and why.

The brief's idea is Breakout Score = Player Form x Matchup Advantage x Team
Expected Points. Multiplying the three at face value assumes each is fully
real. Here each part's weight is learned from past games instead:

    score = w0 + w1 * level + w2 * minutes form + w3 * rate form
               + w4 * matchup + w5 * team

    level         valuation (PIR) expected at the player's usual minutes and rate
    minutes form  extra valuation if his last five games' minutes hold
    rate form     extra valuation if his last five games' rate holds
    matchup       extra valuation from what the opponent has allowed his
                  position, above what those players normally produce
    team          extra valuation from his team being expected to score more
                  (or less) than it usually does

Two lists come out of it. "top" ranks players by score: who should produce
most. Measured on past rounds it is no better than ranking by season average,
because the differences between players dwarf everything else. "rising" ranks
regular rotation players by lift, the form and matchup parts of the score:
who should beat his own norm. That list does better than chance on past
rounds from about round 7 on; in a season's first six rounds it has shown no
edge, because there is too little of the season to measure form or matchups.

Each part is kept separately, so the dashboard can show why a player is listed.
The matchup is based on position (guard, forward, center), not on court zones.
"""

from collections import defaultdict

import numpy as np

RATE_SHRINK_SECONDS = 200 * 60  # season rate is pulled towards the earlier-seasons rate
FORM_SHRINK_SECONDS = 60 * 60  # last-five rate is pulled towards the season rate
MATCHUP_SHRINK_SECONDS = 400 * 60  # opponent's allowance is pulled towards zero
PRIOR_GAMES = 3  # season average per game is pulled towards the earlier-seasons average
PARTS = ["level", "minutes_form", "rate_form", "matchup", "team"]
# The "rising" list ranks by these parts. The team part is left out: on its
# own it picked no better than chance on past rounds, and with it in, the
# list was worse (edge over other rotation players +0.91 against +1.30).
LIFT_PARTS = ["minutes_form", "rate_form", "matchup"]
ROTATION_LEVEL = 8.0  # the "rising" list only considers players at or above this level
LIST_SIZE = 10
NEW_SIGNING_DAYS = 14  # an unseen player registered this recently is expected to play

CANDIDATES_SQL = """
SELECT f.season_code, f.game_code, f.asof_utc, g.round, g.phase, g.played AS game_played,
       f.team_code, f.opponent_code, f.player_id, f.player_name, f.position,
       f.registered_since, ft.games_before AS team_games_before,
       f.times_listed, f.games_played, f.season_seconds, f.season_valuation,
       f.last5_seconds, f.last5_valuation, f.last5_total_seconds, f.recently_played,
       f.true_shooting, f.plays_per_minute,
       pr.prior_valuation_per_second, pr.prior_seconds_per_game,
       ft.off_rating * ft.pace / 100 AS team_usual_points,
       b.seconds, b.valuation, b.points, b.ast, b.is_starter
FROM features_player AS f
JOIN games AS g USING (season_code, game_code)
JOIN player_prior AS pr USING (season_code, player_id)
JOIN features_team AS ft
  ON ft.season_code = f.season_code AND ft.game_code = f.game_code AND ft.team_code = f.team_code
LEFT JOIN box_player AS b
  ON b.season_code = f.season_code AND b.game_code = f.game_code AND b.player_id = f.player_id
ORDER BY f.asof_utc, f.game_code, f.player_id
"""


def load_candidates(db, expected_points: dict[tuple[str, int, str], float]) -> list[dict]:
    """Return one row per game and player expected to play, in playing order,
    with the parts of the score filled in.

    expected_points maps (season, game, team) to the points the rating model
    expected of that team before the game. A player is expected to play if he
    played in one of the last three games he was listed for. One who has not
    been listed yet counts only at his team's first game of the season or
    within NEW_SIGNING_DAYS of his registration; otherwise a registered player
    who never appears is taken to be a long-term absentee.
    """
    cursor = db.execute(CANDIDATES_SQL)
    names = [c[0] for c in cursor.description]
    rows = []
    for record in cursor.fetchall():
        r = dict(zip(names, record))
        key = (r["season_code"], r["game_code"], r["team_code"])
        new_signing = (r["asof_utc"] - r["registered_since"]).days <= NEW_SIGNING_DAYS
        unseen_but_expected = r["times_listed"] == 0 and (r["team_games_before"] == 0 or new_signing)
        if key not in expected_points or not (r["recently_played"] or unseen_but_expected):
            continue
        rate = (r["season_valuation"] + RATE_SHRINK_SECONDS * r["prior_valuation_per_second"]) / (
            r["season_seconds"] + RATE_SHRINK_SECONDS
        )
        recent_rate = ((r["last5_valuation"] or 0) + FORM_SHRINK_SECONDS * rate) / (
            (r["last5_total_seconds"] or 0) + FORM_SHRINK_SECONDS
        )
        if r["games_played"]:
            usual_seconds = r["season_seconds"] / r["games_played"]
            recent_seconds = r["last5_seconds"]
        else:
            usual_seconds = recent_seconds = r["prior_seconds_per_game"]
        prior_per_game = r["prior_valuation_per_second"] * r["prior_seconds_per_game"]
        played = bool(r["seconds"])
        rows.append(
            {
                **r,
                "rate": rate,
                "expected_seconds": recent_seconds,
                "level": usual_seconds * rate,
                "minutes_form": (recent_seconds - usual_seconds) * rate,
                "rate_form": recent_seconds * (recent_rate - rate),
                "team_expected_points": expected_points[key],
                "team_ratio": expected_points[key] / r["team_usual_points"] if r["team_usual_points"] else 1.0,
                "season_average": (r["season_valuation"] + PRIOR_GAMES * prior_per_game)
                / (r["games_played"] + PRIOR_GAMES),
                "played": played,
                "actual": (r["valuation"] if played else 0) if r["game_played"] else None,
            }
        )
    _add_matchup(rows)
    for r in rows:
        r["team"] = r["level"] * (r["team_ratio"] - 1)
    return rows


def _add_matchup(rows: list[dict]) -> None:
    """Fill matchup_per_40 and matchup for rows in playing order.

    For every finished game, each player's valuation minus what his own
    season rate would give in the minutes he played is charged to the team
    that defended him, under his position. Before a game, the opponent's
    running total per second (pulled towards zero) says how much extra it
    allows that position. Games with the same tip-off never see each other.
    """
    allowed = defaultdict(lambda: [0.0, 0.0])
    pending, tipoff = [], None
    for r in rows:
        if r["asof_utc"] != tipoff:
            for key, extra, seconds in pending:
                allowed[key][0] += extra
                allowed[key][1] += seconds
            pending, tipoff = [], r["asof_utc"]
        extra, seconds = allowed[(r["season_code"], r["opponent_code"], r["position"])]
        per_second = extra / (seconds + MATCHUP_SHRINK_SECONDS)
        r["matchup_per_40"] = per_second * 2400
        r["matchup"] = per_second * r["expected_seconds"]
        if r["game_played"] and r["played"]:
            pending.append(
                (
                    (r["season_code"], r["opponent_code"], r["position"]),
                    r["valuation"] - r["seconds"] * r["rate"],
                    r["seconds"],
                )
            )


def fit_weights(rows: list[dict]) -> np.ndarray:
    """Least-squares weights (intercept first, then PARTS) from games in
    which the player took the court."""
    train = [r for r in rows if r["game_played"] and r["played"]]
    X = np.array([[1.0] + [r[part] for part in PARTS] for r in train])
    y = np.array([r["actual"] for r in train], dtype=float)
    return np.linalg.lstsq(X, y, rcond=None)[0]


def add_scores(rows: list[dict], weights: np.ndarray) -> None:
    """Add to each row: score (learned weights), lift (the form and matchup
    parts of the score), and score_product (the brief's formula at face value:
    form x matchup x team)."""
    for r in rows:
        weighted = {part: float(w * r[part]) for w, part in zip(weights[1:], PARTS)}
        r["weighted"] = weighted
        r["score"] = float(weights[0]) + sum(weighted.values())
        r["lift"] = sum(weighted[part] for part in LIFT_PARTS)
        form = r["level"] + r["minutes_form"] + r["rate_form"]
        matchup_ratio = 1 + r["matchup"] / r["level"] if r["level"] > 0 else 1.0
        r["score_product"] = form * matchup_ratio * r["team_ratio"]


def pick(rows: list[dict], which: str) -> list[dict]:
    """Return the ten rows of one list ("top" or "rising") from one round's
    scored rows."""
    if which == "top":
        return sorted(rows, key=lambda r: -r["score"])[:LIST_SIZE]
    return sorted((r for r in rows if r["level"] >= ROTATION_LEVEL), key=lambda r: -r["lift"])[:LIST_SIZE]


BREAKOUT_SCORES_DDL = """CREATE TABLE IF NOT EXISTS breakout_scores (
    run_id VARCHAR, season_code VARCHAR, round INTEGER, game_code INTEGER, list VARCHAR, rank INTEGER,
    player_id VARCHAR, player_name VARCHAR, team_code VARCHAR, opponent_code VARCHAR, position VARCHAR,
    score DOUBLE, lift DOUBLE, level DOUBLE, minutes_form DOUBLE, rate_form DOUBLE, matchup DOUBLE, team DOUBLE,
    matchup_per_40 DOUBLE, team_expected_points DOUBLE, expected_minutes DOUBLE, matchup_basis VARCHAR)"""


def players_to_watch(db, run_id: str, season: str, rows: list[dict], n_rounds: int = 2) -> dict:
    """Score the next rounds' players with weights learned from every played
    game, store both lists under the run id, and return them as
    {round: {"top": [...], "rising": [...]}}. rows are candidate rows from
    load_candidates; those marked absent are left off the lists.

    The stored parts are the weighted ones, in valuation points, so that
    level + minutes_form + rate_form + matchup + team + the intercept = score.
    """
    weights = fit_weights(rows)
    upcoming = [r for r in rows if r["season_code"] == season and not r["game_played"] and not r.get("absent")]
    add_scores(upcoming, weights)
    db.execute(BREAKOUT_SCORES_DDL)
    lists = {}
    for round_number in sorted({r["round"] for r in upcoming})[:n_rounds]:
        in_round = [r for r in upcoming if r["round"] == round_number]
        lists[round_number] = {which: pick(in_round, which) for which in ("top", "rising")}
        for which, picked in lists[round_number].items():
            for rank, r in enumerate(picked, start=1):
                db.execute(
                    "INSERT INTO breakout_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'position')",
                    [
                        run_id,
                        season,
                        round_number,
                        r["game_code"],
                        which,
                        rank,
                        r["player_id"],
                        r["player_name"],
                        r["team_code"],
                        r["opponent_code"],
                        r["position"],
                        r["score"],
                        r["lift"],
                        *(r["weighted"][part] for part in PARTS),
                        r["matchup_per_40"],
                        r["team_expected_points"],
                        r["expected_seconds"] / 60,
                    ],
                )
    return lists
