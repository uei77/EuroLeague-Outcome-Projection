"""Builds the pre-game player features behind "Players to Watch".

One row per game and per player registered with either club at tip-off.
Everything a row contains comes from games that tipped off strictly earlier
in the same season, plus the player's value from earlier seasons.
"""

from elsim.features.roster import newcomer_rate, player_value

# The same rule as team_history in asof.py, for players: a candidate is a
# player registered with a club at a game's tip-off, and his history is his
# own box score lines from earlier games of the season, for any club.
PLAYER_HISTORY_SQL = """
CREATE OR REPLACE TEMP VIEW player_history AS
WITH sides AS (
    SELECT season_code, game_code, tipoff_utc, home_code AS team_code, away_code AS opponent_code
    FROM games WHERE status <> 'Cancelled'
    UNION ALL
    SELECT season_code, game_code, tipoff_utc, away_code, home_code
    FROM games WHERE status <> 'Cancelled'
),
candidates AS (
    SELECT s.season_code, s.game_code, s.tipoff_utc AS asof_utc, s.team_code, s.opponent_code,
           p.player_id, any_value(p.name) AS player_name, any_value(p.position) AS position,
           min(p.start_date) AS registered_since
    FROM sides AS s
    JOIN people AS p
      ON p.season_code = s.season_code AND p.team_code = s.team_code AND p.type = 'J'
     AND p.start_date <= s.tipoff_utc AND p.end_date >= s.tipoff_utc
    GROUP BY ALL
)
SELECT c.*, g.tipoff_utc AS past_tipoff, b.seconds, b.valuation, b.points, b.ast,
       b.fga2 + b.fga3 AS fga, b.fta, b.tov,
       row_number() OVER (PARTITION BY c.season_code, c.game_code, c.player_id
                          ORDER BY g.tipoff_utc DESC NULLS LAST) AS listed_recency,
       CASE WHEN b.seconds > 0 THEN
           row_number() OVER (PARTITION BY c.season_code, c.game_code, c.player_id, b.seconds > 0
                              ORDER BY g.tipoff_utc DESC) END AS played_recency
FROM candidates AS c
LEFT JOIN (box_player AS b JOIN games AS g USING (season_code, game_code))
       ON b.season_code = c.season_code AND b.player_id = c.player_id AND g.tipoff_utc < c.asof_utc
"""

# What each position produced against each team in each finished game:
# the raw material for "where does this opponent concede most".
POSITION_ALLOWED_SQL = """
CREATE OR REPLACE TABLE position_allowed AS
SELECT b.season_code, b.game_code, g.tipoff_utc, t.opponent_code AS team_code, p.position,
       sum(b.valuation) AS valuation, sum(b.seconds) AS seconds
FROM box_player AS b
JOIN games AS g USING (season_code, game_code)
JOIN team_game_stats AS t USING (season_code, game_code, team_code)
JOIN (SELECT DISTINCT season_code, team_code, player_id, position FROM people WHERE type = 'J') AS p
  USING (season_code, team_code, player_id)
WHERE b.seconds > 0
GROUP BY ALL
"""

MATCHUP_SHRINK_SECONDS = 400 * 60  # an opponent's rate is pulled towards the league's as if by 400 extra minutes

# matchup is how much valuation per minute the opponent has allowed to the
# player's position so far this season, divided by the league's rate for that
# position over the same period. Above 1 means the opponent is weak there.
# It is based on position (guard, forward, center), not on court zones.
FEATURES_PLAYER_SQL = f"""
CREATE OR REPLACE TABLE features_player AS
WITH own AS (
    SELECT season_code, game_code, asof_utc, team_code, opponent_code, player_id, player_name, position,
           registered_since,
           count(past_tipoff) AS times_listed,
           count(*) FILTER (seconds > 0) AS games_played,
           coalesce(sum(seconds) FILTER (seconds > 0), 0) AS season_seconds,
           coalesce(sum(valuation) FILTER (seconds > 0), 0) AS season_valuation,
           sum(points) FILTER (seconds > 0) AS season_points,
           sum(fga) FILTER (seconds > 0) AS season_fga,
           sum(fta) FILTER (seconds > 0) AS season_fta,
           sum(tov) FILTER (seconds > 0) AS season_tov,
           avg(seconds) FILTER (played_recency <= 5) AS last5_seconds,
           sum(valuation) FILTER (played_recency <= 5) AS last5_valuation,
           sum(seconds) FILTER (played_recency <= 5) AS last5_total_seconds,
           sum(fga + 0.44 * fta + tov) FILTER (played_recency <= 5) AS last5_plays,
           -- did he play in any of the last three games he was listed for?
           coalesce(bool_or(seconds > 0) FILTER (listed_recency <= 3 AND past_tipoff IS NOT NULL), false) AS recently_played
    FROM player_history
    GROUP BY ALL
),
allowed AS (
    SELECT o.season_code, o.game_code, o.player_id,
           sum(a.valuation) FILTER (a.team_code = o.opponent_code) AS opp_valuation,
           sum(a.seconds) FILTER (a.team_code = o.opponent_code) AS opp_seconds,
           sum(a.valuation) AS league_valuation, sum(a.seconds) AS league_seconds
    FROM own AS o
    LEFT JOIN position_allowed AS a
      ON a.season_code = o.season_code AND a.position = o.position AND a.tipoff_utc < o.asof_utc
    GROUP BY ALL
)
SELECT own.*,
       season_points / nullif(2 * (season_fga + 0.44 * season_fta), 0) AS true_shooting,
       (season_fga + 0.44 * season_fta + season_tov) / nullif(season_seconds / 60.0, 0) AS plays_per_minute,
       last5_plays / nullif(last5_total_seconds / 60.0, 0) AS last5_plays_per_minute,
       coalesce(
           ((coalesce(opp_valuation, 0) + {MATCHUP_SHRINK_SECONDS} * league_valuation / league_seconds)
            / (coalesce(opp_seconds, 0) + {MATCHUP_SHRINK_SECONDS}))
           / (league_valuation / league_seconds), 1.0) AS matchup
FROM own JOIN allowed USING (season_code, game_code, player_id)
"""

PLAYER_PRIOR_DDL = """season_code VARCHAR, player_id VARCHAR, prior_valuation_per_second DOUBLE,
    prior_seconds_per_game DOUBLE, known BOOLEAN"""


def build_player_prior(db) -> None:
    """Create player_prior: each registered player's value from earlier
    seasons (see roster.player_value). The first season of the data has no
    rows, because there is nothing earlier to judge by."""
    seasons = [r[0] for r in db.execute("SELECT DISTINCT season_code FROM games ORDER BY 1").fetchall()]
    player_seasons = {
        (s, p): (sec, val, played)
        for s, p, sec, val, played in db.execute(
            """SELECT season_code, player_id, sum(seconds), sum(valuation), count(*)
           FROM box_player WHERE seconds > 0 GROUP BY ALL"""
        ).fetchall()
    }
    rows = []
    for season in seasons[1:]:
        earlier = [s for s in seasons if s < season]
        newcomer = newcomer_rate(player_seasons, earlier)
        players = db.execute(
            "SELECT DISTINCT player_id FROM people WHERE season_code = ? AND type = 'J'", [season]
        ).fetchall()
        for (player,) in players:
            per_40, seconds_per_game, known = player_value(player, earlier, player_seasons, newcomer)
            rows.append([season, player, per_40 / 2400, seconds_per_game, known])
    db.execute(f"CREATE OR REPLACE TABLE player_prior ({PLAYER_PRIOR_DDL})")
    db.executemany("INSERT INTO player_prior VALUES (?, ?, ?, ?, ?)", rows)


def build_features_player(db, history_sql: str = PLAYER_HISTORY_SQL) -> None:
    db.execute(POSITION_ALLOWED_SQL)
    db.execute(history_sql)
    db.execute(FEATURES_PLAYER_SQL)
