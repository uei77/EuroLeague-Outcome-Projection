"""Stage two: corrects the rating model's forecast with pre-game context.

Two candidates are trained on the same information: a regularised logistic
regression and a small LightGBM. Player absences are not used: for past games
they are only known from the box score, that is, after the game.
"""

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# Pre-game features of both teams, one row per game. Everything comes from
# features_team, which only uses games before tip-off.
FEATURES_SQL = """
SELECT g.season_code, g.game_code,
       h.games_before AS home_games, a.games_before AS away_games,
       least(h.rest_days, 7) AS home_rest, least(a.rest_days, 7) AS away_rest,
       h.last5_net_rating - (h.off_rating - h.def_rating) AS home_form,
       a.last5_net_rating - (a.off_rating - a.def_rating) AS away_form,
       h.orb_rate AS home_orb, h.opp_orb_rate AS home_orb_allowed,
       a.orb_rate AS away_orb, a.opp_orb_rate AS away_orb_allowed,
       h.tov_rate AS home_tov, h.opp_tov_rate AS home_tov_forced,
       a.tov_rate AS away_tov, a.opp_tov_rate AS away_tov_forced,
       h.efg AS home_efg, h.opp_efg AS home_efg_allowed,
       a.efg AS away_efg, a.opp_efg AS away_efg_allowed,
       h.ft_rate AS home_ft, a.ft_rate AS away_ft, h.pace AS home_pace, a.pace AS away_pace
FROM games AS g
JOIN features_team AS h ON h.season_code = g.season_code AND h.game_code = g.game_code AND h.team_code = g.home_code
JOIN features_team AS a ON a.season_code = g.season_code AND a.game_code = g.game_code AND a.team_code = g.away_code
"""

RAW = [
    "home_games",
    "away_games",
    "home_rest",
    "away_rest",
    "home_form",
    "away_form",
    "home_orb",
    "home_orb_allowed",
    "away_orb",
    "away_orb_allowed",
    "home_tov",
    "home_tov_forced",
    "away_tov",
    "away_tov_forced",
    "home_efg",
    "home_efg_allowed",
    "away_efg",
    "away_efg_allowed",
    "home_ft",
    "away_ft",
    "home_pace",
    "away_pace",
]


def load_features(db) -> dict[tuple[str, int], dict]:
    cursor = db.execute(FEATURES_SQL)
    names = [c[0] for c in cursor.description]
    return {(r[0], r[1]): dict(zip(names, r)) for r in cursor.fetchall()}


def _number(value) -> float:
    return np.nan if value is None else float(value)


def gbm_matrix(rows: list[dict]) -> np.ndarray:
    """Rating forecast plus the raw pre-game features; missing stays missing."""
    return np.array(
        [[r["s1_margin"], r["s1_sd"], float(r["neutral"])] + [_number(r[name]) for name in RAW] for r in rows]
    )


def logistic_matrix(rows: list[dict], centre: dict[str, float]) -> np.ndarray:
    """A handful of differences and mismatches; a missing value counts as no
    difference. A mismatch is the product of how far one team is above average
    at something and how far its opponent is above average at allowing it."""

    def off(row, name):
        value = _number(row[name])
        return 0.0 if np.isnan(value) else value - centre[name]

    def diff(row, home, away):
        value = _number(row[home]) - _number(row[away])
        return 0.0 if np.isnan(value) else value

    return np.array(
        [
            [
                r["s1_margin"] / r["s1_sd"],
                float(r["neutral"]),
                diff(r, "home_rest", "away_rest"),
                diff(r, "home_form", "away_form"),
                off(r, "home_orb") * off(r, "away_orb_allowed") - off(r, "away_orb") * off(r, "home_orb_allowed"),
                off(r, "home_tov") * off(r, "away_tov_forced") - off(r, "away_tov") * off(r, "home_tov_forced"),
                float(min(r["home_games"], r["away_games"]) < 5),
            ]
            for r in rows
        ]
    )


def fit_predict(train: list[dict], test: list[dict], seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Train both candidates on train and return their home-win probabilities
    for test, as (logistic, lightgbm). Rows need s1_margin, s1_sd, neutral,
    home_won and the columns of FEATURES_SQL."""
    y = np.array([r["home_won"] for r in train], dtype=int)
    centre = {name: float(np.nanmean([_number(r[name]) for r in train])) for name in RAW}

    logistic = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
    logistic.fit(logistic_matrix(train, centre), y)
    p_logistic = logistic.predict_proba(logistic_matrix(test, centre))[:, 1]

    gbm = LGBMClassifier(
        n_estimators=150,
        learning_rate=0.03,
        num_leaves=4,
        min_child_samples=50,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=5.0,
        random_state=seed,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )
    gbm.fit(gbm_matrix(train), y)
    p_gbm = gbm.predict_proba(gbm_matrix(test))[:, 1]
    return p_logistic, p_gbm
