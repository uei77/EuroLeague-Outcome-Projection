"""Checks the expected-score evaluation on hand-made games."""

from elsim.models.score import evaluate


def game(season, home_pts, away_pts, real_home, real_away):
    return {
        "season_code": season,
        "home_pace": 70.0,
        "away_pace": 70.0,
        "s1_home_per_100": home_pts / 0.7,
        "s1_away_per_100": away_pts / 0.7,
        "s1_sd": 15.0,
        "s1_total_sd": 20.0,
        "home_score": real_home,
        "away_score": real_away,
    }


def test_errors_are_measured_in_points_and_against_earlier_seasons():
    rows = [game("S1", 80, 75, 80, 75), game("S1", 80, 75, 90, 70), game("S2", 85, 80, 81, 84)]
    result = evaluate(rows)
    assert result["games"] == 3
    assert abs(result["home"][0] - (0 + 10 + 4) / 3) < 1e-9
    # S2's baseline is S1's average score (85-72.5); S1 has no earlier season and uses all rows
    assert abs(result["margin"][0] - (0 + 15 + 8) / 3) < 1e-9
    assert 0 <= result["margin_80"] <= 1 and 0 <= result["total_80"] <= 1
