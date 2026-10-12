"""Checks the hand-entered absences and what they do to a forecast."""

import duckdb
import pytest

from elsim.players.absences import fit_absence_effect, load_absences, mark_absent, missing_level


def database():
    db = duckdb.connect()
    db.execute(
        "CREATE TABLE people (season_code VARCHAR, team_code VARCHAR, player_id VARCHAR, name VARCHAR, type VARCHAR)"
    )
    db.execute("INSERT INTO people VALUES ('E2026', 'IST', 'P1', 'JAMES, MIKE', 'J')")
    return db


def write(tmp_path, monkeypatch, line: str) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "absences.csv").write_text(
        "player_name,team_code,until,source,note\n" + line + "\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)


def test_a_listed_player_is_absent_until_his_date_and_not_after(tmp_path, monkeypatch):
    from datetime import datetime

    write(tmp_path, monkeypatch, '"JAMES, MIKE",IST,2026-10-20,source,note')
    absent = load_absences(database(), "E2026")
    row = lambda day: {
        "game_played": False,
        "player_id": "P1",
        "asof_utc": datetime(2026, 10, day, 18),
        "level": 15.0,
        "season_code": "E2026",
        "game_code": day,
        "team_code": "IST",
    }
    rows = [row(14), row(20), row(22)]
    mark_absent(rows, absent, curve=[0.0, 0.2, 0.4])
    assert [r["absent"] for r in rows] == [True, True, False]
    # The second game missed counts for less: the rating model has learned 20% of it by then.
    assert missing_level(rows) == {("E2026", 14, "IST"): 15.0, ("E2026", 20, "IST"): 12.0}


def test_an_unknown_name_stops_the_run_instead_of_being_guessed(tmp_path, monkeypatch):
    write(tmp_path, monkeypatch, '"JAMES, MICHAEL",IST,2026-10-20,source,note')
    with pytest.raises(SystemExit, match="not registered"):
        load_absences(database(), "E2026")


def test_effect_is_learned_from_past_games():
    # Three past games in which the home team missed players and did worse than forecast.
    history = [
        {
            "season_code": "S",
            "game_code": g,
            "home_code": "A",
            "away_code": "B",
            "forecast_margin": 5.0,
            "actual_margin": 5.0 - 0.1 * lost,
        }
        for g, lost in ((1, 10), (2, 20), (3, 30))
    ]
    missing = {("S", g, "A"): lost for g, lost in ((1, 10.0), (2, 20.0), (3, 30.0))}
    effect = fit_absence_effect(missing, history)
    assert abs(effect + 0.1) < 1e-9


def test_rating_model_learns_a_lasting_drop_gradually():
    import csv
    from pathlib import Path

    from elsim.models.state_space import Game, Params
    from elsim.players.absences import absorption_curve

    path = Path(__file__).parent / "fixtures" / "team_game_stats_E2025.csv"
    with open(path, newline="", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: (r["tipoff_utc"], r["game_code"]))
    games = [
        Game(
            "E2025",
            r["team_code"],
            r["opponent_code"],
            False,
            100.0 * int(r["points"]) / int(r["possessions"]),
            100.0 * int(r["opp_points"]) / int(r["opp_possessions"]),
        )
        for r in rows
        if r["is_home"] == "true"
    ]
    params = Params(game_var=0.16, season_var=3.8, carry_over=0.44, noise_var=165.0, new_team_var=16.0, noise_corr=0.2)
    curve = absorption_curve(games, params, {})
    assert curve[0] == 0.0  # nothing learned before the first game without him
    # The learned share grows with games. It is not perfectly smooth, because part of
    # the drop is at first put down to the opponents the team happened to meet.
    assert 0.0 < curve[1] < curve[5] < curve[15] < curve[25] < 1.0
    assert curve[1] < 0.2
