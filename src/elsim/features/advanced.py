"""Advanced statistics per player and team season, from the box scores.

Player shares (usage, rebound, assist, steal, block percentages) are measured
against what the team and the opponent did while the player was on the floor,
estimated from his share of the team's minutes in each game.
"""

PLAYER_ADVANCED_SQL = """
CREATE OR REPLACE TABLE player_advanced AS
WITH team AS (
    SELECT season_code, game_code, team_code, sum(seconds) AS seconds,
           sum(fga2 + fga3) AS fga, sum(fgm2 + fgm3) AS fgm, sum(fta) AS fta, sum(tov) AS tov,
           sum(oreb) AS oreb, sum(dreb) AS dreb
    FROM box_player GROUP BY ALL
),
game AS (
    SELECT b.*, b.seconds * 5.0 / t.seconds AS on_floor,
           t.fga AS t_fga, t.fgm AS t_fgm, t.fta AS t_fta, t.tov AS t_tov, t.oreb AS t_oreb, t.dreb AS t_dreb,
           o.fga AS o_fga, o.fga - o.fgm AS o_missed2_and_3, o.oreb AS o_oreb, o.dreb AS o_dreb, p.possessions AS o_possessions
    FROM box_player AS b
    JOIN team AS t USING (season_code, game_code, team_code)
    JOIN team AS o ON o.season_code = b.season_code AND o.game_code = b.game_code AND o.team_code <> b.team_code
    JOIN team_game_stats AS p ON p.season_code = b.season_code AND p.game_code = b.game_code AND p.team_code = o.team_code
    WHERE b.seconds > 0
)
SELECT season_code, player_id, any_value(player_name) AS player_name, any_value(team_code) AS team_code,
       count(*) AS games, sum(seconds) / 60.0 AS minutes,
       sum(points) / (2 * (sum(fga2 + fga3) + 0.44 * sum(fta))) AS ts_pct,
       (sum(fgm2 + fgm3) + 0.5 * sum(fgm3)) / nullif(sum(fga2 + fga3), 0) AS efg_pct,
       sum(fga3) / nullif(sum(fga2 + fga3), 0) AS three_rate,
       sum(fta) / nullif(sum(fga2 + fga3), 0) AS ft_rate,
       (sum(fga2 + fga3) + 0.44 * sum(fta) + sum(tov)) / sum(on_floor * (t_fga + 0.44 * t_fta + t_tov)) AS usg_pct,
       sum(ast) / nullif(sum(on_floor * t_fgm) - sum(fgm2 + fgm3), 0) AS ast_pct,
       sum(oreb) / sum(on_floor * (t_oreb + o_dreb)) AS orb_pct,
       sum(dreb) / sum(on_floor * (t_dreb + o_oreb)) AS drb_pct,
       sum(stl) / sum(on_floor * o_possessions) AS stl_pct,
       sum(blk) / nullif(sum(on_floor * o_fga), 0) AS blk_pct,
       sum(tov) / nullif(sum(fga2 + fga3) + 0.44 * sum(fta) + sum(tov), 0) AS tov_pct,
       2400.0 * sum(valuation) / sum(seconds) AS pir_per_40
FROM game GROUP BY season_code, player_id
"""

TEAM_ADVANCED_SQL = """
CREATE OR REPLACE TABLE team_advanced AS
SELECT season_code, team_code, count(*) AS games,
       100.0 * sum(points) / sum(possessions) AS off_rating,
       100.0 * sum(opp_points) / sum(opp_possessions) AS def_rating,
       100.0 * sum(points) / sum(possessions) - 100.0 * sum(opp_points) / sum(opp_possessions) AS net_rating,
       2400.0 * sum((possessions + opp_possessions) / 2.0) / sum(seconds) AS pace,
       sum(points) / (2 * (sum(fga) + 0.44 * sum(fta))) AS ts_pct,
       (sum(fgm) + 0.5 * sum(fgm3)) / sum(fga) AS efg_pct,
       sum(tov) / sum(possessions) AS tov_pct,
       sum(oreb) / sum(oreb + opp_dreb) AS orb_pct,
       sum(fta) / sum(fga) AS ft_rate,
       sum(opp_points) / (2 * (sum(opp_fga) + 0.44 * sum(opp_fta))) AS opp_ts_pct,
       (sum(opp_fgm) + 0.5 * sum(opp_fgm3)) / sum(opp_fga) AS opp_efg_pct,
       sum(opp_tov) / sum(opp_possessions) AS opp_tov_pct,
       sum(dreb) / sum(dreb + opp_oreb) AS drb_pct,
       sum(opp_fta) / sum(opp_fga) AS opp_ft_rate
FROM team_game_stats GROUP BY ALL
"""


def build_advanced(db) -> None:
    db.execute(PLAYER_ADVANCED_SQL)
    db.execute(TEAM_ADVANCED_SQL)
