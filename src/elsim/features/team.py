"""Builds per-game team facts and the pre-game team features derived from them."""

from elsim.features.asof import TEAM_HISTORY_SQL

# What each team did in each game it played. These are facts about a finished
# game, not features; features are built from them through team_history.
TEAM_GAME_STATS_SQL = """
CREATE OR REPLACE TABLE team_game_stats AS
WITH possession_counts AS (
    SELECT season_code, game_code, team_code, count(*) AS possessions
    FROM possessions GROUP BY ALL
),
game_length AS (
    SELECT season_code, game_code, max(end_second) AS seconds
    FROM lineup_stints GROUP BY ALL
),
own AS (
    SELECT b.*, p.possessions
    FROM box_team AS b JOIN possession_counts AS p USING (season_code, game_code, team_code)
)
SELECT
    own.season_code, own.game_code, own.team_code, opp.team_code AS opponent_code,
    own.is_home, g.tipoff_utc, l.seconds,
    own.possessions, opp.possessions AS opp_possessions,
    own.points, opp.points AS opp_points,
    own.fga2 + own.fga3 AS fga, own.fgm2 + own.fgm3 AS fgm, own.fgm3, own.fta, own.tov, own.oreb, own.dreb,
    opp.fga2 + opp.fga3 AS opp_fga, opp.fgm2 + opp.fgm3 AS opp_fgm, opp.fgm3 AS opp_fgm3,
    opp.fta AS opp_fta, opp.tov AS opp_tov, opp.oreb AS opp_oreb, opp.dreb AS opp_dreb
FROM own
JOIN own AS opp
    ON opp.season_code = own.season_code AND opp.game_code = own.game_code AND opp.team_code <> own.team_code
JOIN games AS g ON g.season_code = own.season_code AND g.game_code = own.game_code
JOIN game_length AS l ON l.season_code = own.season_code AND l.game_code = own.game_code
"""

# One row per team and game, played or not yet played. Rates are ratios of
# sums over the earlier games, so a game with more possessions counts for more.
# off_rating and def_rating are points per 100 possessions; pace is possessions
# per 40 minutes. They are not adjusted for opponent strength; that is the job
# of the rating model.
FEATURES_TEAM_SQL = """
CREATE OR REPLACE TABLE features_team AS
SELECT
    season_code, game_code, team_code, asof_utc,
    count(tipoff_utc) AS games_before,
    date_diff('minute', max(tipoff_utc), asof_utc) / 1440.0 AS rest_days,
    100.0 * sum(points) / sum(possessions) AS off_rating,
    100.0 * sum(opp_points) / sum(opp_possessions) AS def_rating,
    2400.0 * sum((possessions + opp_possessions) / 2.0) / sum(seconds) AS pace,
    (sum(fgm) + 0.5 * sum(fgm3)) / sum(fga) AS efg,
    1.0 * sum(tov) / sum(possessions) AS tov_rate,
    1.0 * sum(oreb) / sum(oreb + opp_dreb) AS orb_rate,
    1.0 * sum(fta) / sum(fga) AS ft_rate,
    (sum(opp_fgm) + 0.5 * sum(opp_fgm3)) / sum(opp_fga) AS opp_efg,
    1.0 * sum(opp_tov) / sum(opp_possessions) AS opp_tov_rate,
    1.0 * sum(opp_oreb) / sum(opp_oreb + dreb) AS opp_orb_rate,
    1.0 * sum(opp_fta) / sum(opp_fga) AS opp_ft_rate,
    100.0 * (sum(points) FILTER (is_home) / sum(possessions) FILTER (is_home)
           - sum(opp_points) FILTER (is_home) / sum(opp_possessions) FILTER (is_home)) AS home_net_rating,
    100.0 * (sum(points) FILTER (NOT is_home) / sum(possessions) FILTER (NOT is_home)
           - sum(opp_points) FILTER (NOT is_home) / sum(opp_possessions) FILTER (NOT is_home)) AS away_net_rating,
    100.0 * (sum(points) FILTER (recency <= 5) / sum(possessions) FILTER (recency <= 5)
           - sum(opp_points) FILTER (recency <= 5) / sum(opp_possessions) FILTER (recency <= 5)) AS last5_net_rating
FROM (
    SELECT *, row_number() OVER (PARTITION BY season_code, game_code, team_code ORDER BY tipoff_utc DESC) AS recency
    FROM team_history
)
GROUP BY season_code, game_code, team_code, asof_utc
"""


def build_team_game_stats(db) -> None:
    db.execute(TEAM_GAME_STATS_SQL)


def build_features_team(db, history_sql: str = TEAM_HISTORY_SQL) -> None:
    db.execute(history_sql)
    db.execute(FEATURES_TEAM_SQL)
