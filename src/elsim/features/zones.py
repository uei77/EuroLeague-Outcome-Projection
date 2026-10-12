"""Season summaries by court zone, from the shot data: where each player
shoots from and how well, and what each team allows from where.

These tables describe; they do not feed the forecasts. A zone-based matchup
was built and measured against the position-based one on 47,000 player-games:
on its own it had a small effect, and next to the position-based matchup it
added nothing (see docs/TECHNICAL_NOTES.md). So Players to Watch keeps the position basis.
"""

ZONE_PLAYER_SQL = """
CREATE OR REPLACE TABLE zone_player_season AS
SELECT season_code, player_id, zone,
       count(*) AS attempts, sum(made::INTEGER) AS made, sum(made::INTEGER * value) AS points,
       count(*) / sum(count(*)) OVER (PARTITION BY season_code, player_id) AS share_of_attempts,
       sum(made::INTEGER * value) / count(*) AS points_per_shot
FROM shots
GROUP BY season_code, player_id, zone
"""

# The defending team is the other team of the game.
ZONE_TEAM_SQL = """
CREATE OR REPLACE TABLE zone_team_allowed_season AS
WITH faced AS (
    SELECT s.season_code, CASE WHEN s.team_code = g.home_code THEN g.away_code ELSE g.home_code END AS team_code,
           s.zone, s.made, s.value
    FROM shots AS s JOIN games AS g USING (season_code, game_code)
),
by_team AS (
    SELECT season_code, team_code, zone, count(*) AS attempts, sum(made::INTEGER * value) AS points
    FROM faced GROUP BY ALL
),
league AS (
    SELECT season_code, zone, count(*) AS attempts, sum(made::INTEGER * value) AS points
    FROM shots GROUP BY ALL
)
SELECT t.season_code, t.team_code, t.zone, t.attempts, t.points,
       t.attempts / sum(t.attempts) OVER (PARTITION BY t.season_code, t.team_code) AS share_of_attempts,
       t.points / t.attempts AS points_per_shot,
       l.attempts / sum(l.attempts) OVER (PARTITION BY t.season_code, t.team_code) AS league_share_of_attempts,
       l.points / l.attempts AS league_points_per_shot
FROM by_team AS t JOIN league AS l USING (season_code, zone)
"""


def build_zone_tables(db) -> None:
    db.execute(ZONE_PLAYER_SQL)
    db.execute(ZONE_TEAM_SQL)
