"""Asks how much knowing a team's absences could improve the game forecasts.

For past games we know, after the fact, which rotation players did not play.
Here that is handed to the model as if it had been known before tip-off: the
best case for any injury information. The size of the effect is still learned
only from seasons before the one being forecast.
"""

from math import erf, log, sqrt

from elsim.models.state_space import run
from elsim.players.absences import absorption_curve, fit_absence_effect, mark_absent, missing_level

STAR_LEVEL = 15.0  # a player at or above this level is called a star here
FRESH_GAMES = 5  # an absence is fresh during the first games missed in a row


def _loss(p: float, won: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -log(p if won else 1 - p)


def run_backtest(
    rows: list[dict], games: list, season_start: dict, settings_by_season: dict, candidates: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Return (one record per forecast game, one record per game in which
    exactly one team was missing a star who had just gone out).

    rows and games are the model inputs in playing order; candidates are the
    player rows from load_candidates. The first season with fitted settings
    is skipped, because its effect would be learned from a single season.
    """
    all_games, star_games = [], []
    for season in sorted(settings_by_season)[1:]:
        params = settings_by_season[season]
        predictions = run(games, params, season_start)
        curve = absorption_curve([g for g in games if g.season < season], params, season_start)
        mark_absent(candidates, {}, curve)
        missing = missing_level(candidates)
        history = [
            {**r, "forecast_margin": p.margin_per_100, "actual_margin": r["home_per_100"] - r["away_per_100"]}
            for r, p in zip(rows, predictions)
            if r["played"] and r["season_code"] < season
        ]
        effect = fit_absence_effect(missing, history)

        stars, streak = {}, {}
        for r in candidates:
            if r["game_played"]:
                key = (r["season_code"], r["player_id"])
                missed = streak.get(key, 0)
                if r["absent"] and r["level"] >= STAR_LEVEL and missed < FRESH_GAMES:
                    stars[(r["season_code"], r["game_code"], r["team_code"])] = True
                streak[key] = missed + 1 if r["absent"] else 0

        for r, p in zip(rows, predictions):
            if not (r["played"] and r["season_code"] == season):
                continue
            key = (season, r["game_code"])
            home_won = r["home_score"] > r["away_score"]
            shift = effect * (missing.get(key + (r["home_code"],), 0.0) - missing.get(key + (r["away_code"],), 0.0))
            informed = 0.5 * (1 + erf((p.margin_per_100 + shift) / (p.margin_sd * sqrt(2))))
            all_games.append(
                {"season": season, "model": _loss(p.p_home, home_won), "informed": _loss(informed, home_won)}
            )
            home_star, away_star = key + (r["home_code"],) in stars, key + (r["away_code"],) in stars
            if home_star != away_star:
                sign = 1 if home_star else -1
                star_games.append(
                    {
                        "season": season,
                        "p_weakened": p.p_home if home_star else 1 - p.p_home,
                        "weakened_won": home_won == home_star,
                        "margin_miss": sign * ((r["home_per_100"] - r["away_per_100"]) - p.margin_per_100),
                    }
                )
    return all_games, star_games
