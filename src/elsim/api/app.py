"""Read-only API over the latest model run.

Run from the project root:  python -m uvicorn elsim.api.app:app
Every response carries the id of the run its numbers come from.
"""

import duckdb
from fastapi import FastAPI

from elsim import settings as settings_module
from elsim.api import queries

app = FastAPI(title="EuroLeague forecasts", description="Personal, non-commercial. Read-only.")


def _answer(build) -> dict:
    """Open the database read-only, find the latest run and wrap build's result with its id."""
    settings = settings_module.load()
    with duckdb.connect(settings["db_path"], read_only=True) as db:
        run = queries.latest_run(db)
        return {"run_id": run["run_id"], "data": build(db, run, settings["current_season"])}


@app.get("/run")
def run() -> dict:
    return _answer(lambda db, run, season: {**run, "absences": queries.absences(db, run["run_id"], season)})


@app.get("/games")
def games() -> dict:
    return _answer(lambda db, run, season: queries.games(db, run["run_id"], season))


@app.get("/explanations")
def explanations() -> dict:
    """Why each forecast is what it is: its parts, and the left-out factors with their measured size."""
    return _answer(lambda db, run, season: queries.explanations(db, run["run_id"]))


@app.get("/players")
def players() -> dict:
    return _answer(lambda db, run, season: queries.players(db, run["run_id"]))


@app.get("/simulation")
def simulation() -> dict:
    return _answer(lambda db, run, season: queries.simulation(db, run["run_id"], season))


@app.get("/track-record")
def track_record() -> dict:
    return _answer(lambda db, run, season: queries.track_record(db, season))


@app.get("/zones")
def zones() -> dict:
    """What each team allows from each court zone. Empty when the shot module is off."""
    return _answer(lambda db, run, season: queries.zones_allowed(db, season))
