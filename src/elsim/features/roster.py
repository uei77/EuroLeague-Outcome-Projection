"""How strong each team's registered roster looks from earlier seasons, at
every game's tip-off.

Two player values are combined: a box-score one (box_value.py: box scores
and advanced statistics weighted as they go with lineup values) and a lineup
one (lineup_value.py). PIR per 40 minutes is still used for the expected
minutes of players and of newcomers. Everything uses only seasons before the
one in question, plus the list of people registered with the club at the
game's tip-off, so signings and departures during a season are seen.
"""

from collections import defaultdict
from datetime import timedelta
from statistics import mean, pstdev

from elsim.features.box_value import fit_box_value, load_player_seasons, newcomer_box_value
from elsim.features.lineup_value import SEASONS_USED, coach_lookup, fit_values, load_stints, newcomer_value

SHRINK_SECONDS = 400 * 60  # a player's rate is pulled towards the newcomer rate as if by 400 extra minutes
SEASON_DECAY = 0.5  # each season further back counts half as much
ROTATION_SIZE = 10  # the roster index averages the ten players expected to play most
RECENT_GAMES = 3  # a registered player counts as available if he played in one of the team's last three games
NEW_SIGNING_DAYS = 14  # ... or was registered after those games began, or within the last 14 days

ROSTER_DDL = """season_code VARCHAR, game_code INTEGER, team_code VARCHAR, asof_utc TIMESTAMP,
    box_index DOUBLE, lineup_index DOUBLE, box_z DOUBLE, lineup_z DOUBLE, roster_z DOUBLE,
    registered INTEGER, known_players INTEGER, available INTEGER, available_z DOUBLE, known_absences_z DOUBLE,
    available_players VARCHAR"""


def newcomer_rate(player_seasons: dict, earlier: list[str]) -> tuple[float, float]:
    """Return (valuation per second, seconds per game) of players in their
    first season here, measured over the earlier seasons. The very first
    season in the data is skipped, because everyone looks new in it."""
    seen = {player for (season, player) in player_seasons if season == earlier[0]}
    valuation = seconds = games = 0
    for season in earlier[1:]:
        this_season = {p: v for (s, p), v in player_seasons.items() if s == season}
        for player, (sec, val, played) in this_season.items():
            if player not in seen:
                valuation, seconds, games = valuation + val, seconds + sec, games + played
        seen |= set(this_season)
    if seconds == 0:  # only one earlier season: fall back to everyone in it
        totals = [v for (s, _), v in player_seasons.items() if s == earlier[0]]
        seconds, valuation, games = (sum(t[i] for t in totals) for i in range(3))
    return valuation / seconds, seconds / games


def player_value(
    player: str, earlier: list[str], player_seasons: dict, newcomer: tuple[float, float]
) -> tuple[float, float, bool]:
    """Return (valuation per 40 minutes, expected seconds per game, known)
    for one player from the earlier seasons only. A player with no earlier
    games gets the newcomer rate and is marked as not known."""
    valuation = seconds = 0.0
    weight = 1.0
    recent_seconds = None
    for season in reversed(earlier):
        if (season, player) in player_seasons:
            sec, val, played = player_seasons[(season, player)]
            valuation += weight * val
            seconds += weight * sec
            if recent_seconds is None:
                recent_seconds = sec / played
        weight *= SEASON_DECAY
    rate = (valuation + SHRINK_SECONDS * newcomer[0]) / (seconds + SHRINK_SECONDS)
    return rate * 2400, recent_seconds or newcomer[1], seconds > 0


def roster_index(values: list[tuple[float, float, float, bool]]) -> tuple[float, float, int]:
    """Return (box index, lineup index, known players) of a roster, each index
    the minutes-weighted average over the players expected to play most.
    values holds (box value, seconds per game, lineup value, known) per player."""
    top = sorted(values, key=lambda v: -v[1])[:ROTATION_SIZE]
    seconds = sum(v[1] for v in top)
    return (sum(v[0] * v[1] for v in top) / seconds, sum(v[2] * v[1] for v in top) / seconds, sum(v[3] for v in top))


def build_roster_strength(db, current: str | None = None, absent: dict | None = None) -> None:
    """Create roster_by_game (each team at each game's tip-off) and
    season_start (the same at the team's first game of the season).

    available_z is the same index over the registered players expected to be
    available: those who played in one of the team's last three games, or
    joined after those games began, or within the last 14 days. It uses only
    games finished before the tip-off. For games not yet played this rule is
    applied to each team's next game only; later games count every registered
    player, as nobody knows who will be missing by then.

    known_absences_z is available_z with the hand-entered absences (absent:
    {player_id: last day absent}) also left out of the current season's
    games not yet played.

    Both indexes are turned into z-scores with the mean and spread of the
    teams' first games of that season, so a change during the season is
    measured on the same scale; roster_z is the z-score of their sum. Rows are
    missing in the first season of the data, which has no earlier season."""
    seasons = [r[0] for r in db.execute("SELECT DISTINCT season_code FROM games ORDER BY 1").fetchall()]
    player_seasons = {
        (s, p): (sec, val, played)
        for s, p, sec, val, played in db.execute(
            """SELECT season_code, player_id, sum(seconds), sum(valuation), count(*)
           FROM box_player WHERE seconds > 0 GROUP BY ALL"""
        ).fetchall()
    }
    registrations = defaultdict(list)
    for season, team, player, start, end in db.execute(
        "SELECT season_code, team_code, player_id, start_date, end_date FROM people WHERE type = 'J'"
    ).fetchall():
        registrations[(season, team)].append((player, start, end))
    games = db.execute(
        """SELECT season_code, game_code, tipoff_utc, home_code, away_code, played FROM games
           WHERE status <> 'Cancelled' ORDER BY tipoff_utc, game_code"""
    ).fetchall()
    absent = absent or {}
    stints = load_stints(db)
    box_seasons = load_player_seasons(db)
    coach_at = coach_lookup(db)
    played = defaultdict(set)
    for season, game, team, player in db.execute(
        "SELECT season_code, game_code, team_code, player_id FROM box_player WHERE seconds > 0"
    ).fetchall():
        played[(season, game, team)].add(player)

    rows = []
    for season in seasons[1:]:
        earlier = [s for s in seasons if s < season]
        box_newcomer = newcomer_rate(player_seasons, earlier)
        lineup, coach_values = fit_values(stints, earlier[-SEASONS_USED:])
        lineup_newcomer = newcomer_value(lineup, player_seasons, earlier)
        learned = fit_box_value(lineup, box_seasons, earlier[-SEASONS_USED:])
        box_values = {p: learned(p, earlier) for p in {p for (s, p) in box_seasons if s < season}}
        box_newcomer_value = newcomer_box_value([v for v in box_values.values() if v is not None])
        cache = {}

        def value(player):
            if player not in cache:
                _, seconds, known = player_value(player, earlier, player_seasons, box_newcomer)
                box = box_values.get(player) if known else None
                cache[player] = (
                    box_newcomer_value if box is None else box,
                    seconds,
                    lineup.get(player, lineup_newcomer) if known else lineup_newcomer,
                    known,
                )
            return cache[player]

        season_rows, first, recent, waiting = [], {}, defaultdict(list), set()
        for _, game, tipoff, home, away, game_played in (g for g in games if g[0] == season):
            for team in (home, away):
                coach = coach_values.get(coach_at(season, team, tipoff), 0.0) / 5  # a coach acts on all five
                registered = {p: start for p, start, end in registrations[(season, team)] if start <= tipoff <= end}
                if not registered:
                    continue
                box, lineup_index, known = roster_index([value(p) for p in registered])
                lineup_index += coach
                last = recent[team][-RECENT_GAMES:]
                later_game = not game_played and team in waiting
                if not game_played:
                    waiting.add(team)
                if last and not later_game:
                    seen = set().union(*(players for _, players in last))
                    available = [
                        p
                        for p, start in registered.items()
                        if p in seen or start > last[0][0] or tipoff - start <= timedelta(days=NEW_SIGNING_DAYS)
                    ]
                else:
                    available = list(registered)
                known_available = available
                if season == current and not game_played:
                    known_available = [p for p in available if not (p in absent and tipoff <= absent[p])]
                indexes = []
                for players in (available, known_available):
                    box_part, lineup_part, _ = roster_index([value(p) for p in players or registered])
                    indexes.append((box_part, lineup_part + coach))
                row = [
                    season,
                    game,
                    team,
                    tipoff,
                    box,
                    lineup_index,
                    None,
                    None,
                    None,
                    len(registered),
                    known,
                    len(available),
                    *indexes,
                    "|".join(sorted(available or registered)),
                ]
                season_rows.append(row)
                first.setdefault(team, row)
                if (season, game, team) in played:
                    recent[team].append((tipoff, played[(season, game, team)]))
        starts = list(first.values())
        centre = {k: mean(r[k] for r in starts) for k in (4, 5)}
        spread = {k: pstdev(r[k] for r in starts) for k in (4, 5)}
        for row in season_rows:
            row[6], row[7] = ((row[k] - centre[k]) / spread[k] for k in (4, 5))
        sums = [r[6] + r[7] for r in starts]
        for row in season_rows:
            row[8] = (row[6] + row[7] - mean(sums)) / pstdev(sums)
            for column in (12, 13):
                total = sum((row[column][i] - centre[k]) / spread[k] for i, k in enumerate((4, 5)))
                row[column] = (total - mean(sums)) / pstdev(sums)
            # An absence can lift a minutes-weighted average when the player
            # left out rates below the one who moves up; a hand-entered
            # absence is never allowed to make a team stronger.
            row[13] = min(row[13], row[12])
        rows += season_rows

    db.execute(f"CREATE OR REPLACE TABLE roster_by_game ({ROSTER_DDL})")
    db.executemany(f"INSERT INTO roster_by_game VALUES ({', '.join('?' * 15)})", rows)
    db.execute("""CREATE OR REPLACE TABLE season_start AS
        SELECT * EXCLUDE (game_code) FROM roster_by_game
        QUALIFY row_number() OVER (PARTITION BY season_code, team_code ORDER BY asof_utc, game_code) = 1""")
