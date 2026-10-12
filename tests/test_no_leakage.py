"""A feature of a game must not change when that game and everything after it
is removed from the data. If it does, the feature used the future.

Runs on the real 2025-26 season (games and per-game team facts).
"""

from pathlib import Path

import duckdb

from elsim.features.asof import TEAM_HISTORY_SQL
from elsim.features.team import build_features_team

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_GAME_CODES = [5, 40, 77, 123, 200, 251, 310, 379, 385, 406]


def database():
    db = duckdb.connect()
    db.execute(f"CREATE TABLE games AS SELECT * FROM read_csv('{(FIXTURES / 'games_E2025.csv').as_posix()}')")
    db.execute(
        f"CREATE TABLE team_game_stats AS SELECT * FROM read_csv('{(FIXTURES / 'team_game_stats_E2025.csv').as_posix()}')"
    )
    return db


def features_of(db, game_code: int) -> list[tuple]:
    return db.execute("SELECT * FROM features_team WHERE game_code = ? ORDER BY team_code", [game_code]).fetchall()


def leaking_games(history_sql: str) -> list[int]:
    """Return the sampled games whose features change once the game itself
    and all later games are deleted."""
    full = database()
    build_features_team(full, history_sql)
    leaks = []
    for game_code in SAMPLE_GAME_CODES:
        tipoff = full.execute("SELECT tipoff_utc FROM games WHERE game_code = ?", [game_code]).fetchone()[0]
        truncated = database()
        truncated.execute("DELETE FROM team_game_stats WHERE tipoff_utc >= ?", [tipoff])
        build_features_team(truncated, history_sql)
        if features_of(full, game_code) != features_of(truncated, game_code):
            leaks.append(game_code)
    return leaks


def test_features_use_only_games_before_tipoff():
    assert leaking_games(TEAM_HISTORY_SQL) == []


def test_the_check_catches_a_deliberate_leak():
    # Letting a game count towards its own features must be detected.
    leaky = TEAM_HISTORY_SQL.replace("prior.tipoff_utc < target.tipoff_utc", "prior.tipoff_utc <= target.tipoff_utc")
    assert leaky != TEAM_HISTORY_SQL
    assert leaking_games(leaky) == SAMPLE_GAME_CODES


def test_first_round_has_no_history_and_the_final_has_a_full_season():
    db = database()
    build_features_team(db)
    games_before = lambda game_code: [row[4] for row in features_of(db, game_code)]
    assert games_before(5) == [0, 0]  # round 1
    assert len(games_before(406)) == 2 and min(games_before(406)) >= 38  # the final
