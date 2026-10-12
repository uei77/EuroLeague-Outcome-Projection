"""Pre-game values of the factors that were measured and not adopted by the
forecast (docs/TECHNICAL_NOTES.md, "Tried and not adopted"). They are kept so each forecast
can show what they would say and how large they have been on past games.

Every value is from the home team's side (home minus away) and uses only
data from before the game's tip-off, except the league averages used for
centring, which come from earlier seasons.
"""

from collections import defaultdict

FACTORS = {
    # name: (label, unit)
    "home_away": (
        "Home and away form: how much better each team has played at home than away this season",
        "points per 100",
    ),
    "rest": ("Rest days, home minus away (EuroLeague games only, capped at 4)", "day"),
    "travel": ("Travel, away minus home", "1,000 km"),
    "shooting": ("Shooting matchup: effective field-goal % against the opponent's allowed %", "product of rates"),
    "rebounding": ("Offensive rebounding against the opponent's allowed rate", "product of rates"),
    "turnovers": ("Turnovers committed against the opponent's forced rate", "product of rates"),
    "zones": ("Shot-zone matchup: where a team shoots against where the opponent concedes", "points per 100 shots"),
    "style": ("Shot-zone matchup with each team's profile blended from its players' habits", "points per 100 shots"),
    "coach": ("Head coach's earlier EuroLeague win rate, shrunk by 20 games", "share above 0.5"),
    "crowd": (
        "Home crowd: the home team's average attendance so far, against the league's (log scale)",
        "log attendance",
    ),
    "referees": ("Referees: how much better home teams have done in this crew's earlier games", "points per 100"),
}

FACTOR_INPUTS_DDL = "season_code VARCHAR, game_code INTEGER, " + ", ".join(f"{name} DOUBLE" for name in FACTORS)

EARLY_GAMES = 5  # season-to-date rates count for g / (g + 5) after g games
ZONE_SHRINK_SHOTS = 50  # an opponent's allowed make rate per zone is pulled to the league's by 50 shots
ZONE_MIN_SHOTS = 200  # fewer shots so far and the zone matchup is left at zero
STYLE_BLEND_SHOTS = 400  # the players' habits count as much as 400 of the team's own shots this season
COACH_SHRINK_GAMES = 20
FORM_SHRINK_GAMES = 10  # a team's home-away split so far counts for g / (g + 10) after g games
CROWD_SHRINK_GAMES = 5  # a team's attendance so far is pulled to the league's by 5 games
REFEREE_SHRINK_GAMES = 50
POINTS = {"above-break three": 3, "corner three": 3}

MATCHUPS = {
    "shooting": ("efg", "opp_efg"),
    "rebounding": ("orb_rate", "opp_orb_rate"),
    "turnovers": ("tov_rate", "opp_tov_rate"),
}

LEAGUE_SQL = """
SELECT season_code,
       (sum(fgm) + 0.5 * sum(fgm3)) / sum(fga) AS efg,
       1.0 * sum(oreb) / sum(oreb + opp_dreb) AS orb_rate,
       1.0 * sum(tov) / sum(possessions) AS tov_rate
FROM team_game_stats GROUP BY 1 ORDER BY 1
"""


def _league_centres(db) -> dict[str, dict[str, float]]:
    """Per season, the league's rates over the earlier seasons (the first
    season uses its own)."""
    seasons = db.execute(LEAGUE_SQL).fetchall()
    centres = {}
    for i, (season, *_rates) in enumerate(seasons):
        earlier = seasons[:i] or seasons[:1]
        centres[season] = {
            k: sum(r[j + 1] for r in earlier) / len(earlier) for j, k in enumerate(("efg", "orb_rate", "tov_rate"))
        }
    return centres


def _matchups(db) -> dict[tuple, dict[str, float]]:
    centres = _league_centres(db)
    features = {
        (s, g, t): (n, row)
        for s, g, t, n, *row in db.execute(
            "SELECT season_code, game_code, team_code, games_before, efg, opp_efg, orb_rate, opp_orb_rate, "
            "tov_rate, opp_tov_rate FROM features_team"
        ).fetchall()
    }
    columns = ["efg", "opp_efg", "orb_rate", "opp_orb_rate", "tov_rate", "opp_tov_rate"]
    out = {}
    for s, g, home, away in db.execute(
        "SELECT season_code, game_code, home_code, away_code FROM games WHERE status <> 'Cancelled'"
    ).fetchall():
        values = {}
        for name, (own, allowed) in MATCHUPS.items():
            h, a = features.get((s, g, home)), features.get((s, g, away))
            if not h or not a or not h[0] or not a[0] or s not in centres:
                values[name] = 0.0
                continue
            hv, av = dict(zip(columns, h[1])), dict(zip(columns, a[1]))
            if None in (hv[own], hv[allowed], av[own], av[allowed]):
                values[name] = 0.0
                continue
            c = centres[s][own]
            weight = h[0] / (h[0] + EARLY_GAMES) * a[0] / (a[0] + EARLY_GAMES)
            values[name] = weight * ((hv[own] - c) * (av[allowed] - c) - (av[own] - c) * (hv[allowed] - c))
        out[(s, g)] = values
    return out


def _home_away(db) -> dict[tuple, float]:
    """Home team's home form plus away team's away form, each as how far the
    team's (home net rating - away net rating) / 2 so far this season lies
    above the league's usual value in earlier seasons."""
    usual = {}
    seasons = db.execute(
        """SELECT season_code, avg(split) FROM (
               SELECT season_code, team_code,
                      (100.0 * sum(points - opp_points) FILTER (is_home) / sum(possessions) FILTER (is_home)
                     - 100.0 * sum(points - opp_points) FILTER (NOT is_home) / sum(possessions) FILTER (NOT is_home)) / 2 AS split
               FROM team_game_stats GROUP BY ALL) GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    for i, (season, _) in enumerate(seasons):
        earlier = seasons[:i] or seasons[:1]
        usual[season] = sum(v for _, v in earlier) / len(earlier)
    split = {
        (s, g, t): (n, (h - a) / 2)
        for s, g, t, n, h, a in db.execute(
            """SELECT season_code, game_code, team_code, games_before, home_net_rating, away_net_rating
           FROM features_team WHERE home_net_rating IS NOT NULL AND away_net_rating IS NOT NULL"""
        ).fetchall()
    }
    out = {}
    for s, g, home, away in db.execute(
        "SELECT season_code, game_code, home_code, away_code FROM games WHERE status <> 'Cancelled'"
    ).fetchall():
        value = 0.0
        for team in (home, away):
            if (s, g, team) in split and s in usual:
                n, v = split[(s, g, team)]
                value += n / (n + FORM_SHRINK_GAMES) * (v - usual[s])
        out[(s, g)] = value
    return out


def _crowd_and_referees(db, order: list[tuple]) -> tuple[dict[tuple, float], dict[tuple, float]]:
    """Return, as of each tip-off, (1) the home team's average log attendance
    in its home games of this and the previous season (the previous one at
    half weight), shrunk to the league's average, minus the league's average;
    and (2) the assigned referees' average home bias: home margin per 100
    possessions minus the league's average in all their earlier games, shrunk
    towards zero. Games without reported attendance or referees count as
    unknown; unassigned referees give zero."""
    from math import log

    info = {
        (s, g): (aud, refs)
        for s, g, aud, refs in db.execute(
            "SELECT season_code, game_code, audience, referee_codes FROM games"
        ).fetchall()
    }
    margin = {
        (s, g): m
        for s, g, m in db.execute(
            """SELECT season_code, game_code, 100.0 * points / possessions - 100.0 * opp_points / opp_possessions
           FROM team_game_stats WHERE is_home"""
        ).fetchall()
    }
    crowd = defaultdict(list)  # (season, team) -> log attendance of home games
    league_crowd = []
    referee = defaultdict(lambda: [0.0, 0])
    margin_sum = margin_n = 0
    seasons = sorted({o[0] for o in order})
    crowd_out, referee_out = {}, {}
    for s, g, _, home, _away, played in order:
        previous = seasons[seasons.index(s) - 1] if seasons.index(s) else None
        values = [(v, 1.0) for v in crowd[(s, home)]] + [(v, 0.5) for v in crowd[(previous, home)]]
        if league_crowd:
            centre = sum(league_crowd[-500:]) / len(league_crowd[-500:])
            weight = sum(w for _, w in values)
            mean = (sum(v * w for v, w in values) + CROWD_SHRINK_GAMES * centre) / (weight + CROWD_SHRINK_GAMES)
            crowd_out[(s, g)] = mean - centre
        else:
            crowd_out[(s, g)] = 0.0
        audience, refs = info.get((s, g), (None, None))
        codes = refs.split("|") if refs else []
        referee_out[(s, g)] = (
            sum(referee[r][0] / (referee[r][1] + REFEREE_SHRINK_GAMES) for r in codes) / len(codes) if codes else 0.0
        )
        if not played:
            continue
        if audience:
            crowd[(s, home)].append(log(audience))
            league_crowd.append(log(audience))
        if (s, g) in margin:
            average = margin_sum / margin_n if margin_n else 0.0
            for r in codes:
                referee[r][0] += margin[(s, g)] - average
                referee[r][1] += 1
            margin_sum, margin_n = margin_sum + margin[(s, g)], margin_n + 1
    return crowd_out, referee_out


def _zones(db, order: list[tuple]) -> tuple[dict[tuple, float], dict[tuple, float]]:
    """Return two shot-zone matchups as of each tip-off, from the shots of
    earlier games: from the team's own shots so far this season, and from a
    blend of that with the shooting habits of the players it is expected to
    field (STYLE_BLEND_SHOTS)."""
    has_shots = (
        db.execute("SELECT count(*) FROM shots").fetchone()[0]
        if db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'shots'").fetchone()[0]
        else 0
    )
    if not has_shots:
        return {}, {}
    per_game = defaultdict(dict)
    for s, g, t, zone, n, made in db.execute(
        "SELECT season_code, game_code, team_code, zone, count(*), sum(made::INT) FROM shots GROUP BY ALL"
    ).fetchall():
        per_game[(s, g, t)][zone] = (n, made)
    player_game = defaultdict(lambda: defaultdict(int))
    for s, g, p, zone, n in db.execute(
        "SELECT season_code, game_code, player_id, zone, count(*) FROM shots GROUP BY ALL"
    ).fetchall():
        player_game[(s, g, p)][zone] = n
    minutes = defaultdict(list)  # (season, game, team) -> [(player, seconds)]
    for s, g, t, p, sec in db.execute(
        "SELECT season_code, game_code, team_code, player_id, seconds FROM box_player WHERE seconds > 0"
    ).fetchall():
        minutes[(s, g, t)].append((p, sec))
    taken = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    conceded = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    league = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    habits = defaultdict(lambda: defaultdict(float))  # (season, player) -> zone -> attempts, plus "seconds"
    recent = defaultdict(list)  # (season, team) -> [[(player, seconds)], ...]
    seasons = sorted({o[0] for o in order})
    registered = defaultdict(list)
    for s, t, p, start, end in db.execute(
        "SELECT season_code, team_code, player_id, start_date, end_date FROM people WHERE type = 'J'"
    ).fetchall():
        registered[(s, t)].append((p, start, end))
    per_game_seconds = {
        (s, p): sec / n
        for s, p, sec, n in db.execute(
            "SELECT season_code, player_id, sum(seconds), count(*) FROM box_player WHERE seconds > 0 GROUP BY ALL"
        ).fetchall()
    }

    def habit(season, player):
        """A player's attempts per second by zone: this season so far plus
        earlier seasons, each further back counting half."""
        total, weight = defaultdict(float), 1.0
        for earlier in reversed([x for x in seasons if x <= season]):
            for zone, value in habits[(earlier, player)].items():
                total[zone] += weight * value
            weight *= 0.5
        seconds = total.pop("seconds", 0.0)
        return {zone: n / seconds for zone, n in total.items()} if seconds else {}

    def expected_lineup(season, team, tipoff):
        """Players and seconds expected: those of the team's last three games;
        before its first game, the registered players with their seconds per
        game last season."""
        if recent[(season, team)]:
            return [x for game in recent[(season, team)][-3:] for x in game]
        previous = seasons[seasons.index(season) - 1] if seasons.index(season) else None
        return [
            (p, per_game_seconds.get((previous, p), 0.0))
            for p, start, end in registered[(season, team)]
            if start <= tipoff <= end
        ]

    def profile(season, team, tipoff, blend):
        own = taken[(season, team)]
        n_own = sum(v[0] for v in own.values())
        shares = {zone: v[0] / n_own for zone, v in own.items()} if n_own else {}
        if not blend:
            return shares if n_own >= ZONE_MIN_SHOTS else {}
        expected = defaultdict(float)
        for player, sec in expected_lineup(season, team, tipoff):
            for zone, rate in habit(season, player).items():
                expected[zone] += rate * sec
        n_expected = sum(expected.values())
        if not n_expected:
            return shares
        return {
            zone: (n_own * shares.get(zone, 0.0) + STYLE_BLEND_SHOTS * expected[zone] / n_expected)
            / (n_own + STYLE_BLEND_SHOTS)
            for zone in set(shares) | set(expected)
        }

    def edge(season, team, opponent, tipoff, blend):
        shares, allowed, base = profile(season, team, tipoff, blend), conceded[(season, opponent)], league[season]
        if not blend and sum(v[0] for v in allowed.values()) < ZONE_MIN_SHOTS:
            return 0.0
        total = 0.0
        for zone, share in shares.items():
            league_rate = base[zone][1] / base[zone][0] if base[zone][0] else 0.0
            rate = (allowed[zone][1] + league_rate * ZONE_SHRINK_SHOTS) / (allowed[zone][0] + ZONE_SHRINK_SHOTS)
            total += share * POINTS.get(zone, 2) * (rate - league_rate)
        return 100 * total

    team_only, blended, current = {}, {}, None
    for s, g, tipoff, home, away, played in order:
        if s != current:
            if current is not None:  # start each season's league rates from a tenth of the last one's
                for zone, (n, made) in league[current].items():
                    league[s][zone] = [0.1 * n, 0.1 * made]
            current = s
        team_only[(s, g)] = edge(s, home, away, tipoff, False) - edge(s, away, home, tipoff, False)
        blended[(s, g)] = edge(s, home, away, tipoff, True) - edge(s, away, home, tipoff, True)
        if not played:
            continue
        for team, opponent in ((home, away), (away, home)):
            for zone, (n, made) in per_game[(s, g, team)].items():
                for table, key in ((taken, (s, team)), (conceded, (s, opponent)), (league, s)):
                    table[key][zone][0] += n
                    table[key][zone][1] += made
            recent[(s, team)].append(minutes[(s, g, team)])
            for player, sec in minutes[(s, g, team)]:
                habits[(s, player)]["seconds"] += sec
                for zone, n in player_game[(s, g, player)].items():
                    habits[(s, player)][zone] += n
    return team_only, blended


def _coaches(db, order: list[tuple], home_won: dict[tuple, bool]) -> dict[tuple, float]:
    """Each head coach's earlier EuroLeague record at every tip-off."""
    spells = defaultdict(list)
    for s, t, coach, start, end in db.execute(
        "SELECT season_code, team_code, player_id, start_date, end_date FROM people WHERE type = 'E'"
    ).fetchall():
        spells[(s, t)].append((start, end, coach))
    record = defaultdict(lambda: [0, 0])  # coach -> [games, wins]
    out = {}
    for s, g, tipoff, home, away, played in order:
        coaches, value = [], 0.0
        for sign, team in ((1, home), (-1, away)):
            current = [c for c in spells[(s, team)] if c[0] <= tipoff <= c[1]]
            coach = max(current)[2] if current else None
            coaches.append(coach)
            if coach:
                games, wins = record[coach]
                value += sign * (wins - 0.5 * games) / (games + COACH_SHRINK_GAMES)
        out[(s, g)] = value
        if played:
            for coach, won in zip(coaches, (home_won[(s, g)], not home_won[(s, g)])):
                if coach:
                    record[coach][0] += 1
                    record[coach][1] += won
    return out


def build_factor_inputs(db) -> None:
    """Create the factor_inputs table, one row per scheduled game."""
    order = db.execute(
        """SELECT season_code, game_code, tipoff_utc, home_code, away_code, played FROM games
           WHERE status <> 'Cancelled' ORDER BY tipoff_utc, game_code"""
    ).fetchall()
    home_won = {
        (s, g): h > a
        for s, g, h, a in db.execute(
            "SELECT season_code, game_code, home_score, away_score FROM games WHERE played"
        ).fetchall()
    }
    context = {
        (s, g): (hr - ar, ((at or 0.0) - (ht or 0.0)) / 1000)
        for s, g, hr, ar, ht, at in db.execute(
            "SELECT season_code, game_code, home_rest_days, away_rest_days, home_travel_km, away_travel_km "
            "FROM game_context"
        ).fetchall()
    }
    matchups, coaches, form = _matchups(db), _coaches(db, order, home_won), _home_away(db)
    zones, style = _zones(db, order)
    crowd, referees = _crowd_and_referees(db, order)
    rows = []
    for s, g, *_ in order:
        rest, travel = context.get((s, g), (0.0, 0.0))
        m = matchups.get((s, g), {})
        rows.append(
            [
                s,
                g,
                form.get((s, g), 0.0),
                rest,
                travel,
                *(m.get(name, 0.0) for name in ("shooting", "rebounding", "turnovers")),
                zones.get((s, g), 0.0),
                style.get((s, g), 0.0),
                coaches.get((s, g), 0.0),
                crowd.get((s, g), 0.0),
                referees.get((s, g), 0.0),
            ]
        )
    db.execute(f"CREATE OR REPLACE TABLE factor_inputs ({FACTOR_INPUTS_DDL})")
    db.executemany(f"INSERT INTO factor_inputs VALUES ({', '.join('?' * (2 + len(FACTORS)))})", rows)
