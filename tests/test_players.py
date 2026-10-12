"""Checks the player features and score parts on the real 2025-26 season:
what is known about a player before a game must not change when that game
and everything after it is removed from the data."""

from pathlib import Path

import duckdb

from elsim.features.player import build_features_player
from elsim.features.team import build_features_team
from elsim.players.breakout import PARTS, add_scores, fit_weights, load_candidates, pick

FIXTURES = Path(__file__).parent / "fixtures"
TABLES = ["games", "team_game_stats", "box_player", "people", "player_prior"]
SAMPLE_GAME_CODES = [40, 123, 251, 379]
PRE_GAME = PARTS + ["matchup_per_40", "expected_seconds", "season_average", "rate"]


def candidates(before_game: int | None = None) -> list[dict]:
    """Candidate rows from the full season, or from the season cut off just
    before a game's tip-off."""
    db = duckdb.connect()
    for table in TABLES:
        db.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv('{(FIXTURES / f'{table}_E2025.csv').as_posix()}')")
    if before_game is not None:
        tipoff = db.execute("SELECT tipoff_utc FROM games WHERE game_code = ?", [before_game]).fetchone()[0]
        db.execute("DELETE FROM team_game_stats WHERE tipoff_utc >= ?", [tipoff])
        db.execute(
            "DELETE FROM box_player WHERE game_code IN (SELECT game_code FROM games WHERE tipoff_utc >= ?)", [tipoff]
        )
    build_features_team(db)
    build_features_player(db)
    expected = {
        (s, g, t): 85.0
        for s, g, h, a in db.execute("SELECT season_code, game_code, home_code, away_code FROM games").fetchall()
        for t in (h, a)
    }
    return load_candidates(db, expected)


def pre_game(rows: list[dict], game_code: int) -> dict:
    return {r["player_id"]: [r[field] for field in PRE_GAME] for r in rows if r["game_code"] == game_code}


def test_a_players_pre_game_numbers_use_only_earlier_games():
    full = candidates()
    for game_code in SAMPLE_GAME_CODES:
        known = pre_game(full, game_code)
        assert len(known) >= 16
        assert known == pre_game(candidates(before_game=game_code), game_code)


def test_both_lists_have_ten_players_and_parts_add_up_to_the_score():
    rows = candidates()
    weights = fit_weights(rows)
    in_round = [r for r in rows if r["phase"] == "RS" and r["round"] == 20]
    add_scores(in_round, weights)
    top, rising = pick(in_round, "top"), pick(in_round, "rising")
    assert len(top) == len(rising) == 10
    assert len({r["player_id"] for r in top}) == 10
    for r in top + rising:
        assert abs(weights[0] + sum(r["weighted"].values()) - r["score"]) < 1e-9
