"""Checks the schedule context and the measurement of left-out factors."""

import duckdb
import numpy as np

from elsim.features.context import distance_km
from elsim.features.factors import FACTORS
from elsim.models.explain import factor_effects


def test_distance_between_athens_and_istanbul():
    assert 520 < distance_km((37.98, 23.73), (41.01, 28.98)) < 580
    assert distance_km((44.8, 20.4), (44.8, 20.4)) == 0


def test_factor_effect_is_recovered_from_forecast_errors():
    rng = np.random.default_rng(0)
    db = duckdb.connect()
    db.execute(
        "CREATE TABLE factor_inputs (season_code VARCHAR, game_code INTEGER, "
        + ", ".join(f"{name} DOUBLE" for name in FACTORS)
        + ")"
    )
    history = []
    for g in range(2000):
        values = rng.normal(size=len(FACTORS))
        db.execute(f"INSERT INTO factor_inputs VALUES ('S', {g}, {', '.join(map(str, values))})")
        error = 2.0 * values[list(FACTORS).index("rebounding")] + rng.normal(scale=1.0)
        history.append({"season_code": "S", "game_code": g, "forecast_margin": 0.0, "actual_margin": error})
    effects = factor_effects(db, history)
    assert abs(effects["rebounding"][0] - 2.0) < 4 * effects["rebounding"][1]
    assert abs(effects["shooting"][0]) < 4 * effects["shooting"][1]
    assert "travel" not in effects  # weighed by the rating model itself, not measured here
