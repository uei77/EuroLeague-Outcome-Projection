"""Tests that read real league data from tests/fixtures are left out when the
folder is absent: the data is kept out of the public repository."""

from pathlib import Path

USES_FIXTURES = [
    "test_absences.py",
    "test_lineups.py",
    "test_no_leakage.py",
    "test_parse_odds.py",
    "test_parse_pbp.py",
    "test_players.py",
    "test_shots.py",
    "test_simulator.py",
    "test_state_space.py",
]

collect_ignore = [] if (Path(__file__).parent / "fixtures").exists() else USES_FIXTURES
