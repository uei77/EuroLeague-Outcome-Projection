"""Checks the shot module on a saved real game (E2026 game 1)."""

import json
from pathlib import Path

from elsim.ingest.parse_shots import ZONES, field_goals, zone_of

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_field_goals_agree_with_the_box_score():
    shots = field_goals(load("shots_E2026_1.json"))
    for team in load("boxscore_E2026_1.json")["Stats"]:
        code = team["PlayersStats"][0]["Team"].strip()
        own = [s for s in shots if s["team_code"] == code]
        totals = team["totr"]
        assert sum(s["value"] == 2 for s in own) == totals["FieldGoalsAttempted2"]
        assert sum(s["value"] == 3 for s in own) == totals["FieldGoalsAttempted3"]
        assert sum(s["value"] == 2 and s["made"] for s in own) == totals["FieldGoalsMade2"]
        assert sum(s["value"] == 3 and s["made"] for s in own) == totals["FieldGoalsMade3"]


def test_every_shot_has_one_of_the_six_zones_and_threes_are_never_two_point_zones():
    shots = field_goals(load("shots_E2026_1.json"))
    assert {s["zone"] for s in shots} <= set(ZONES)
    assert all(("three" in s["zone"]) == (s["value"] == 3) for s in shots)


def test_zone_rules():
    assert zone_of("3FGM", "I", 60) == "corner three"
    assert zone_of("3FGA", "H", 700) == "above-break three"
    assert zone_of("2FGM", "A", 5) == "rim"
    assert zone_of("2FGA", "H", 400) == "long two"  # a foot on the line
