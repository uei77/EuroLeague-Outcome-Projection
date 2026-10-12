"""Checks lineup reconstruction against a saved real game (E2026 game 1)."""

import json
from pathlib import Path

from elsim.derive.lineups import rebuild

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def game():
    box = load("boxscore_E2026_1.json")
    return box, rebuild(box, load("playbyplay_E2026_1.json"))


def test_each_team_always_has_five():
    _, (stints, report) = game()
    assert report["bad_five_checks"] == 0
    assert report["bad_substitutions"] == 0
    assert all(stint["five_check_passed"] for stint in stints)


def test_stint_points_equal_box_score():
    box, (stints, _) = game()
    for team in box["Stats"]:
        code = team["PlayersStats"][0]["Team"].strip()
        rebuilt = sum(s["points_for"] for s in stints if s["team_code"] == code)
        assert rebuilt == team["totr"]["Points"]


def test_stints_cover_the_whole_game_without_gaps():
    _, (stints, _) = game()
    one_team = [s for s in stints if s["team_code"] == stints[0]["team_code"]]
    assert one_team[0]["start_second"] == 0
    assert one_team[-1]["end_second"] == 2400
    for earlier, later in zip(one_team, one_team[1:]):
        assert earlier["end_second"] == later["start_second"]


def test_rebuilt_minutes_are_close_to_box_score():
    box, (stints, _) = game()
    seconds = {}
    for stint in stints:
        for player in stint["players"]:
            seconds[player] = seconds.get(player, 0) + stint["end_second"] - stint["start_second"]
    for team in box["Stats"]:
        for player in team["PlayersStats"]:
            if ":" not in (player["Minutes"] or ""):
                continue
            minutes, secs = player["Minutes"].split(":")
            official = int(minutes) * 60 + int(secs)
            assert abs(seconds.get(player["Player_ID"].strip(), 0) - official) <= 30
