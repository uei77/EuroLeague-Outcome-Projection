"""Records every model run, so each stored number can be traced to the code,
settings and seed that produced it."""

import json
import subprocess
from datetime import datetime, timezone

MODEL_RUNS_DDL = """CREATE TABLE IF NOT EXISTS model_runs (
    run_id VARCHAR PRIMARY KEY, created_utc TIMESTAMP, git_sha VARCHAR,
    parameters VARCHAR, seed BIGINT, data_through_utc TIMESTAMP)"""


def git_sha() -> str | None:
    """Return the current commit, or None when the project is not a git repository."""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def record(db, parameters: dict, seed: int) -> str:
    """Store a new run and return its id."""
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    data_through = db.execute("SELECT max(tipoff_utc) FROM games WHERE played").fetchone()[0]
    db.execute(MODEL_RUNS_DDL)
    db.execute(
        "INSERT INTO model_runs VALUES (?, ?, ?, ?, ?, ?)",
        [run_id, now.replace(tzinfo=None), git_sha(), json.dumps(parameters), seed, data_through],
    )
    return run_id
