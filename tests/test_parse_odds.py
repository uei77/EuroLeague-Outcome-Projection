"""Checks that The Odds API team names map onto the right league games.

The events are the 19 games returned by the real snapshot of 10 October 2026
(names and start times as received); the schedule is the league's own.
"""

import json
from pathlib import Path

import pytest

from elsim.ingest.parse_odds import load_aliases, match_game, price_rows

GAMES = json.loads((Path(__file__).parent / "fixtures" / "schedule_E2026_rounds_5_6.json").read_text())

SNAPSHOT_GAMES = [
    ("2026-10-13T17:45:00Z", "Fenerbahce SK", "Žalgiris", 46),
    ("2026-10-13T18:00:00Z", "ASVEL Lyon Villeurbanne", "KK Crvena zvezda", 41),
    ("2026-10-13T18:30:00Z", "Saski Baskonia", "Dubai Basketball", 42),
    ("2026-10-13T18:30:00Z", "FC Barcelona Bàsquet", "Maccabi Tel Aviv", 44),
    ("2026-10-13T18:30:00Z", "KK Partizan NIS", "Panathinaikos", 47),
    ("2026-10-13T18:30:00Z", "Pallacanestro Olimpia Milano", "Real Madrid", 43),
    ("2026-10-13T19:00:00Z", "Valencia Basket", "Olympiacos", 45),
    ("2026-10-14T16:00:00Z", "Hapoel Tel Aviv", "Beşiktaş J.K.", 48),
    ("2026-10-14T17:30:00Z", "Anadolu Efes", "FC Bayern München", 49),
    ("2026-10-14T18:45:00Z", "Paris Basketball", "Virtus Segafredo Bologna", 50),
    ("2026-10-15T18:30:00Z", "Pallacanestro Olimpia Milano", "Dubai Basketball", 51),
    ("2026-10-15T18:30:00Z", "Valencia Basket", "Maccabi Tel Aviv", 52),
    ("2026-10-15T19:00:00Z", "Real Madrid", "ASVEL Lyon Villeurbanne", 53),
    ("2026-10-16T17:00:00Z", "Žalgiris", "Anadolu Efes", 57),
    ("2026-10-16T17:00:00Z", "Beşiktaş J.K.", "FC Bayern München", 55),
    ("2026-10-16T18:00:00Z", "KK Crvena zvezda", "Paris Basketball", 56),
    ("2026-10-16T18:15:00Z", "Panathinaikos", "Hapoel Tel Aviv", 60),
    ("2026-10-16T18:30:00Z", "FC Barcelona Bàsquet", "Olympiacos", 58),
    ("2026-10-16T18:30:00Z", "Virtus Segafredo Bologna", "Saski Baskonia", 59),
]


@pytest.fixture(autouse=True)
def project_root(monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)


def event(start, home, away, bookmakers=()):
    return {"commence_time": start, "home_team": home, "away_team": away, "bookmakers": list(bookmakers)}


def test_every_snapshot_game_maps_to_its_league_game():
    aliases = load_aliases("odds_api")
    assert len(set(aliases.values())) == 20
    for start, home, away, game_code in SNAPSHOT_GAMES:
        assert match_game(event(start, home, away), aliases, GAMES) == game_code


def test_unknown_team_name_is_refused_not_guessed():
    with pytest.raises(ValueError, match="Unknown team name"):
        match_game(event("2026-10-13T17:45:00Z", "Fenerbahce", "Žalgiris"), load_aliases("odds_api"), GAMES)


def test_prices_are_assigned_to_home_and_away_by_name():
    bookmaker = {
        "key": "book",
        "markets": [
            {"key": "h2h", "outcomes": [{"name": "Žalgiris", "price": 3.1}, {"name": "Fenerbahce SK", "price": 1.4}]}
        ],
    }
    snapshot = {
        "snapshot_utc": "2026-10-12T10:00:00Z",
        "events": [event("2026-10-13T17:45:00Z", "Fenerbahce SK", "Žalgiris", [bookmaker])],
    }
    assert price_rows(snapshot, load_aliases("odds_api"), GAMES) == [["2026-10-12T10:00:00Z", 46, "book", 1.4, 3.1]]
