"""Reads one run's results from the database. The API and the dashboard both
use these functions, so they always show the same numbers."""

MARKET_SQL = """
SELECT game_code, median((1 / home_price) / (1 / home_price + 1 / away_price)) AS p_market, count(*) AS bookmakers
FROM odds_snapshots
WHERE season_code = ? AND snapshot_utc = (SELECT max(snapshot_utc) FROM odds_snapshots)
GROUP BY game_code
"""


def _has_table(db, name: str) -> bool:
    return db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0] > 0


def _rows(db, sql: str, parameters: list) -> list[dict]:
    cursor = db.execute(sql, parameters)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def has_run(db) -> bool:
    """True once predict has stored at least one run."""
    return _has_table(db, "model_runs") and db.execute("SELECT count(*) FROM model_runs").fetchone()[0] > 0


def latest_run(db) -> dict:
    """The newest run: id, when it was made, the code version, the seed, the
    last game it knew about and its model settings (as JSON text)."""
    return _rows(
        db,
        """SELECT run_id, created_utc, git_sha, seed, data_through_utc, parameters
                        FROM model_runs ORDER BY created_utc DESC LIMIT 1""",
        [],
    )[0]


def games(db, run_id: str, season: str, n_rounds: int = 2) -> list[dict]:
    """Forecasts for the next n_rounds rounds, with the market's view where a snapshot exists."""
    has_score = db.execute("""SELECT count(*) FROM information_schema.columns
                              WHERE table_name = 'game_predictions' AND column_name = 'home_points'""").fetchone()[0]
    score = (
        "p.home_points, p.away_points, p.total_sd"
        if has_score
        else "NULL AS home_points, NULL AS away_points, NULL AS total_sd"
    )  # runs made before score forecasts
    return _rows(
        db,
        f"""
        WITH market AS ({MARKET_SQL})
        SELECT g.round, g.game_code, g.tipoff_utc, g.home_code, h.name AS home_name, g.away_code, a.name AS away_name,
               p.p_home, p.expected_margin, p.margin_sd, p.p_home_with_absences, p.margin_with_absences,
               p.absence_shift_per_100 <> 0 AS has_absences, m.p_market, coalesce(m.bookmakers, 0) AS bookmakers,
               p.model_used, {score}
        FROM game_predictions AS p
        JOIN games AS g USING (season_code, game_code)
        JOIN teams AS h ON h.season_code = g.season_code AND h.team_code = g.home_code
        JOIN teams AS a ON a.season_code = g.season_code AND a.team_code = g.away_code
        LEFT JOIN market AS m ON m.game_code = g.game_code
        WHERE p.run_id = ? AND g.round IN (
            SELECT DISTINCT g2.round FROM game_predictions AS p2 JOIN games AS g2 USING (season_code, game_code)
            WHERE p2.run_id = ? ORDER BY 1 LIMIT {int(n_rounds)})
        ORDER BY g.tipoff_utc, g.game_code""",
        [season, run_id, run_id],
    )


def explanations(db, run_id: str) -> dict:
    """Each forecast split into its parts, and the factors left out of the
    forecast with their measured size. Empty for runs made before this existed."""
    if not _has_table(db, "game_explanations"):
        return {"games": [], "factors": []}
    return {
        "games": _rows(
            db,
            """SELECT * EXCLUDE (run_id) FROM game_explanations WHERE run_id = ?
                                  ORDER BY game_code, in_forecast DESC""",
            [run_id],
        ),
        "factors": _rows(db, "SELECT * EXCLUDE (run_id) FROM factor_effects WHERE run_id = ?", [run_id]),
    }


def players(db, run_id: str) -> list[dict]:
    """Both Players to Watch lists of the run, every part of the score included."""
    return _rows(
        db,
        """SELECT * EXCLUDE (run_id) FROM breakout_scores WHERE run_id = ?
                        ORDER BY round, list, rank""",
        [run_id],
    )


def simulation(db, run_id: str, season: str) -> list[dict]:
    """Season probabilities per team and scenario. Empty until simulate has been run."""
    if not _has_table(db, "sim_results"):
        return []
    return _rows(
        db,
        """SELECT s.scenario, s.team_code, t.name AS team_name, s.n_paths, s.expected_wins,
                               s.p_play_in, s.p_playoffs, s.p_final_four, s.p_title
                        FROM sim_results AS s
                        JOIN teams AS t ON t.season_code = ? AND t.team_code = s.team_code
                        WHERE s.run_id = ? ORDER BY s.scenario, s.expected_wins DESC""",
        [season, run_id],
    )


def absences(db, run_id: str, season: str) -> list[dict]:
    """The hand-entered absences the run was made with."""
    return _rows(
        db,
        """SELECT DISTINCT p.name AS player_name, p.team_code, a.until
                        FROM run_absences AS a
                        JOIN people AS p ON p.season_code = ? AND p.player_id = a.player_id AND p.type = 'J'
                        WHERE a.run_id = ? ORDER BY 2, 1""",
        [season, run_id],
    )


def track_record(db, season: str) -> list[dict]:
    """Finished games for which we had both a forecast and odds before tip-off.

    For each game: the last forecast stored before it tipped off, and the
    market's probability from the last odds snapshot before it tipped off
    (p_market, the closing line; median bookmaker, each with its own margin
    removed). When there was an earlier snapshot too, p_open is the market at
    the first one and p_model_at_open our last forecast stored before it, for
    closing-line value. Nothing made or fetched after tip-off is used.
    """
    return _rows(
        db,
        """
        WITH forecast AS (
            SELECT p.season_code, p.game_code,
                   arg_max(p.run_id, r.created_utc) AS run_id,
                   arg_max(p.p_home, r.created_utc) AS p_model,
                   arg_max(coalesce(p.p_home_with_absences, p.p_home), r.created_utc) AS p_model_with_absences
            FROM game_predictions AS p
            JOIN model_runs AS r USING (run_id)
            JOIN games AS g USING (season_code, game_code)
            WHERE r.created_utc < g.tipoff_utc
            GROUP BY ALL
        ),
        snapshot AS (
            SELECT o.season_code, o.game_code, min(o.snapshot_utc) AS opening_utc, max(o.snapshot_utc) AS snapshot_utc
            FROM odds_snapshots AS o JOIN games AS g USING (season_code, game_code)
            WHERE o.snapshot_utc < g.tipoff_utc
            GROUP BY ALL
        ),
        prices AS (
            SELECT o.season_code, o.game_code, o.snapshot_utc,
                   median((1 / o.home_price) / (1 / o.home_price + 1 / o.away_price)) AS p, count(*) AS bookmakers
            FROM odds_snapshots AS o GROUP BY ALL
        ),
        market AS (
            SELECT s.season_code, s.game_code, c.p AS p_market, c.bookmakers,
                   CASE WHEN s.opening_utc < s.snapshot_utc THEN op.p END AS p_open, s.opening_utc
            FROM snapshot AS s
            JOIN prices AS c ON c.season_code = s.season_code AND c.game_code = s.game_code AND c.snapshot_utc = s.snapshot_utc
            JOIN prices AS op ON op.season_code = s.season_code AND op.game_code = s.game_code AND op.snapshot_utc = s.opening_utc
        ),
        at_open AS (
            SELECT p.season_code, p.game_code, arg_max(p.p_home, r.created_utc) AS p_model_at_open
            FROM game_predictions AS p
            JOIN model_runs AS r USING (run_id)
            JOIN market AS m USING (season_code, game_code)
            WHERE r.created_utc < m.opening_utc
            GROUP BY ALL
        )
        SELECT g.round, g.game_code, g.tipoff_utc, g.home_code, g.away_code,
               g.home_score > g.away_score AS home_won,
               f.run_id, f.p_model, f.p_model_with_absences, m.p_market, m.bookmakers, m.p_open, a.p_model_at_open
        FROM games AS g
        JOIN forecast AS f USING (season_code, game_code)
        JOIN market AS m USING (season_code, game_code)
        LEFT JOIN at_open AS a USING (season_code, game_code)
        WHERE g.season_code = ? AND g.played
        ORDER BY g.tipoff_utc, g.game_code""",
        [season],
    )


def _has_shots(db) -> bool:
    """True when the shot module was on for the last load."""
    return _has_table(db, "zone_team_allowed_season") and db.execute("SELECT count(*) FROM shots").fetchone()[0] > 0


def zones_allowed(db, season: str) -> list[dict]:
    """What each team has allowed from each zone this season, next to the
    league. Empty when the shot module is off."""
    if not _has_shots(db):
        return []
    return _rows(
        db,
        """SELECT z.team_code, t.name AS team_name, z.zone, z.attempts, z.share_of_attempts,
                               z.league_share_of_attempts, z.points_per_shot, z.league_points_per_shot
                        FROM zone_team_allowed_season AS z
                        JOIN teams AS t USING (season_code, team_code)
                        WHERE z.season_code = ? ORDER BY t.name, z.zone""",
        [season],
    )


def shooters(db, season: str) -> list[dict]:
    """Players with shots this season, most attempts first. Empty when the shot module is off."""
    if not _has_shots(db):
        return []
    return _rows(
        db,
        """SELECT s.player_id, any_value(p.name) AS player_name, any_value(s.team_code) AS team_code,
                               count(*) AS attempts
                        FROM shots AS s
                        JOIN (SELECT DISTINCT player_id, name FROM people WHERE season_code = ? AND type = 'J') AS p
                          USING (player_id)
                        WHERE s.season_code = ? GROUP BY s.player_id ORDER BY attempts DESC""",
        [season, season],
    )


def player_shots(db, season: str, player_id: str) -> list[dict]:
    """One player's field-goal attempts this season, with position."""
    return _rows(
        db,
        """SELECT x, y, made, value, zone FROM shots
                        WHERE season_code = ? AND player_id = ?""",
        [season, player_id],
    )
