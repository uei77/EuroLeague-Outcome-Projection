"""Checks the plain-text forecast files."""

from datetime import datetime

from elsim.report import write_reports


def test_one_block_per_game_and_players_only_for_listed_rounds(tmp_path):
    game = {
        "game_code": 41,
        "round": 5,
        "tipoff_utc": datetime(2026, 10, 13, 17, 45),
        "home_code": "AAA",
        "away_code": "BBB",
        "p_home": 0.7,
        "expected_margin": 5.0,
        "margin_sd": 12.0,
        "home_points": 85.0,
        "away_points": 80.0,
        "total_sd": 15.0,
        "absence_shift": 0.0,
        "p_home_with_absences": 0.7,
    }
    later = {**game, "game_code": 99, "round": 9}
    player = {
        "game_code": 41,
        "game_played": False,
        "team_code": "AAA",
        "player_id": "P1",
        "player_name": "ONE, PLAYER",
        "position": "Guard",
        "expected_seconds": 1500,
        "score": 14.2,
        "lift": 1.1,
    }
    games_file, players_file = write_reports(
        tmp_path, "run", [later, game], [player], {}, {"AAA": "Alpha", "BBB": "Beta"}, [], [5], {("P1", 41)}
    )
    games_text, players_text = games_file.read_text(), players_file.read_text()
    assert games_text.count(" v ") == 2 and games_text.index("round 5") < games_text.index("round 9")
    assert "confident pick" in games_text and "85 - 80" in games_text
    assert "ONE, PLAYER" in players_text and "rising" in players_text and "round 9" not in players_text


def test_a_matchweek_takes_both_rounds_of_a_double_week_and_stops_before_the_next():
    from elsim.report import matchweek, week_label

    day = lambda d: datetime(2026, 10, d, 18)
    games = [
        {"round": 5, "tipoff_utc": day(13)},
        {"round": 5, "tipoff_utc": day(14)},
        {"round": 6, "tipoff_utc": day(16)},
        {"round": 7, "tipoff_utc": day(21)},
    ]
    assert matchweek(games) == [5, 6]
    assert week_label([5, 6]) == "round-05-06" and week_label([7]) == "round-07"
    assert matchweek([g for g in games if g["round"] == 7]) == [7]
