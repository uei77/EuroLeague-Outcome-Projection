"""Checks play-by-play flattening, including a saved real overtime game."""

import json
from pathlib import Path

from elsim.derive.lineups import rebuild
from elsim.ingest.parse_pbp import flatten

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_single_overtime_game_has_five_periods_and_runs_2700_seconds():
    # E2018 game 129 went to one overtime. Its overtime list starts with a
    # "BP" event; many others start with substitutions instead.
    plays = load("playbyplay_E2018_129.json")
    events = flatten(plays)
    assert events[-1]["period"] == 5
    stints, _ = rebuild(load("boxscore_E2018_129.json"), plays)
    assert stints[-1]["end_second"] == 2700


def event(play_type: str, marker: str) -> dict:
    return {"PLAYTYPE": play_type, "MARKERTIME": marker, "NUMBEROFPLAY": 1, "CODETEAM": "AAA", "PLAYER_ID": "P1"}


def test_substitutions_before_begin_period_do_not_add_an_overtime():
    quarter = [event("BP", ""), event("EP", "")]
    plays = {
        "FirstQuarter": quarter,
        "SecondQuarter": quarter,
        "ThirdQuarter": quarter,
        "ForthQuarter": quarter,
        "ExtraTime": [event("IN", "05:00"), event("BP", ""), event("2FGM", "04:00"), event("EG", "")],
    }
    events = flatten(plays)
    assert {e["period"] for e in events} == {1, 2, 3, 4, 5}
    assert events[-1]["elapsed_seconds"] == 2700


def test_broken_clock_marker_keeps_the_previous_clock():
    plays = {"FirstQuarter": [event("BP", ""), event("2FGM", "09:00"), event("AS", "-1:00")]}
    events = flatten(plays)
    assert events[-1]["clock_seconds"] == 540
    assert events[-1]["elapsed_seconds"] == 60
