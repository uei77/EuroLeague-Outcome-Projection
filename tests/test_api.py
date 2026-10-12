"""Checks that the API answers from the database and that every response
carries the id of the run its numbers come from."""

import duckdb
import pytest
from fastapi.testclient import TestClient

from elsim import runs
from elsim import settings as settings_module
from elsim.models.predict import GAME_PREDICTIONS_DDL
from elsim.players.absences import RUN_ABSENCES_DDL
from elsim.players.breakout import BREAKOUT_SCORES_DDL
from elsim.simulate.season import SIM_RESULTS_DDL

RUN_ID = "20261011T000000Z"


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "test.duckdb"
    with duckdb.connect(str(path)) as db:
        for ddl in (runs.MODEL_RUNS_DDL, GAME_PREDICTIONS_DDL, BREAKOUT_SCORES_DDL, SIM_RESULTS_DDL, RUN_ABSENCES_DDL):
            db.execute(ddl)
        for column in ("absence_shift_per_100", "p_home_with_absences", "margin_with_absences"):
            db.execute(f"ALTER TABLE game_predictions ADD COLUMN {column} DOUBLE")
        db.execute("""CREATE TABLE games (season_code VARCHAR, game_code INTEGER, round INTEGER, tipoff_utc TIMESTAMP,
                      home_code VARCHAR, away_code VARCHAR, played BOOLEAN, home_score INTEGER, away_score INTEGER)""")
        db.execute("CREATE TABLE teams (season_code VARCHAR, team_code VARCHAR, name VARCHAR)")
        db.execute(
            "CREATE TABLE people (season_code VARCHAR, team_code VARCHAR, player_id VARCHAR, name VARCHAR, type VARCHAR)"
        )
        db.execute(
            "CREATE TABLE odds_snapshots (snapshot_utc TIMESTAMP, season_code VARCHAR, game_code INTEGER, bookmaker VARCHAR, home_price DOUBLE, away_price DOUBLE)"
        )
        db.execute(f"""INSERT INTO model_runs VALUES ('older', '2026-10-01', NULL, '{{"model": "m"}}', 1, '2026-09-30'),
                       ('late', '2026-10-06', NULL, '{{"model": "m"}}', 1, '2026-10-05'),
                       ('{RUN_ID}', '2026-10-11', 'abc', '{{"model": "m"}}', 1, '2026-10-09')""")
        db.execute("""INSERT INTO games VALUES ('E2026', 49, 5, '2026-10-14 17:30', 'IST', 'MUN', false, 0, 0),
                      ('E2026', 30, 4, '2026-10-05 18:00', 'MUN', 'IST', true, 80, 70)""")
        db.execute(
            "INSERT INTO teams VALUES ('E2026', 'IST', 'Anadolu Efes Istanbul'), ('E2026', 'MUN', 'FC Bayern Munich')"
        )
        db.execute("INSERT INTO people VALUES ('E2026', 'IST', 'P1', 'JAMES, MIKE', 'J')")
        db.execute("""INSERT INTO odds_snapshots VALUES ('2026-10-11', 'E2026', 49, 'book', 1.5, 2.5),
                      ('2026-10-04', 'E2026', 30, 'book', 2.0, 2.0), ('2026-10-06', 'E2026', 30, 'book', 1.01, 50.0)""")
        db.execute(f"""INSERT INTO game_predictions VALUES ('{RUN_ID}', 'E2026', 49, 0.66, 5.1, 12.7, 'm', -1.5, 0.62, 4.0),
                       ('older', 'E2026', 30, 0.7, 6.0, 12.7, 'm', NULL, NULL, NULL),
                       ('late', 'E2026', 30, 0.99, 30.0, 12.7, 'm', 0, 0.99, 30.0)""")
        db.execute(f"INSERT INTO sim_results VALUES ('{RUN_ID}', 'IST', 'baseline', 1000, 17.0, 0.2, 0.2, 0.06, 0.01)")
        db.execute(f"INSERT INTO run_absences VALUES ('{RUN_ID}', 'P1', '2027-06-30')")
        db.execute(f"""INSERT INTO breakout_scores VALUES ('{RUN_ID}', 'E2026', 5, 49, 'top', 1, 'P2', 'LARKIN, SHANE',
                       'IST', 'MUN', 'Guard', 16.0, 0.2, 15.7, 0.0, 0.0, -0.2, 0.3, -0.6, 82.0, 30.4, 'position')""")
    real = settings_module.load()
    monkeypatch.setattr(settings_module, "load", lambda: {**real, "db_path": str(path)})
    from elsim.api.app import app

    return TestClient(app)


@pytest.mark.parametrize("path", ["/run", "/games", "/players", "/simulation"])
def test_every_response_carries_the_latest_run_id(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["run_id"] == RUN_ID
    assert response.json()["data"]


def test_games_show_forecast_market_and_absence_adjustment(client):
    game = client.get("/games").json()["data"][0]
    assert (game["home_name"], game["away_name"]) == ("Anadolu Efes Istanbul", "FC Bayern Munich")
    assert game["p_home"] == 0.66 and game["p_home_with_absences"] == 0.62 and game["has_absences"] is True
    assert abs(game["p_market"] - 0.625) < 1e-9  # (1/1.5) / (1/1.5 + 1/2.5)


def test_run_lists_the_absences_it_was_made_with(client):
    assert client.get("/run").json()["data"]["absences"][0]["player_name"] == "JAMES, MIKE"


def test_track_record_uses_only_forecasts_and_odds_from_before_tip_off(client):
    # Game 30 tipped off on 5 October. The run and the odds snapshot made
    # after that knew the result and must be ignored.
    from elsim.models.market import summarise

    rows = client.get("/track-record").json()["data"]
    assert len(rows) == 1
    game = rows[0]
    assert (game["run_id"], game["p_model"], game["p_model_with_absences"], game["p_market"]) == (
        "older",
        0.7,
        0.7,
        0.5,
    )
    assert game["home_won"] is True
    lines = summarise(rows)
    assert [line["round"] for line in lines] == ["4", "all"]
    assert lines[0]["model"] < lines[0]["market"]  # 0.7 on the winner beats 0.5


def test_closing_line_value_counts_moves_towards_our_forecast():
    from elsim.models.market import closing_line_value

    rows = [
        {"p_open": 0.50, "p_model_at_open": 0.60, "p_market": 0.55},  # we leaned home, market moved home
        {"p_open": 0.50, "p_model_at_open": 0.40, "p_market": 0.52},  # we leaned away, market moved home
        {"p_open": 0.70, "p_model_at_open": 0.60, "p_market": 0.66},  # we leaned away, market moved away
        {"p_open": None, "p_model_at_open": None, "p_market": 0.5},
    ]
    clv = closing_line_value(rows)
    assert clv["moving"] == 3 and abs(clv["share_toward_us"] - 2 / 3) < 1e-9
    assert abs(clv["average_move_toward_us"] - (0.05 - 0.02 + 0.04) / 3) < 1e-9
