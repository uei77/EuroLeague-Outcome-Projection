"""The single place that decides which past games a feature may use.

Every feature of a game is computed "as of" its tip-off: only games of the
same season that tipped off strictly earlier may contribute. All feature
builders must take their history from the team_history view defined here and
must not join game results to features in any other way.
"""

TEAM_HISTORY_SQL = """
CREATE OR REPLACE TEMP VIEW team_history AS
SELECT
    target.season_code, target.game_code, target.team_code,
    target.tipoff_utc AS asof_utc,
    prior.* EXCLUDE (season_code, game_code, team_code)
FROM (
    SELECT season_code, game_code, home_code AS team_code, tipoff_utc FROM games
    UNION ALL
    SELECT season_code, game_code, away_code AS team_code, tipoff_utc FROM games
) AS target
LEFT JOIN team_game_stats AS prior
    ON prior.season_code = target.season_code
    AND prior.team_code = target.team_code
    AND prior.tipoff_utc < target.tipoff_utc
"""
