"""Rebuilds the DuckDB tables from the raw JSON files on disk.

The database is rebuilt from scratch on every run, so it can always be
reproduced from data/raw alone.
"""

import csv
import json
import tempfile
from pathlib import Path

import duckdb

from elsim.derive.lineups import rebuild
from elsim.derive.possessions import split
from elsim.features.advanced import build_advanced
from elsim.features.context import build_game_context, load_venues
from elsim.features.factors import build_factor_inputs
from elsim.features.player import build_features_player, build_player_prior
from elsim.features.roster import build_roster_strength
from elsim.features.team import build_features_team, build_team_game_stats
from elsim.features.zones import build_zone_tables
from elsim.ingest.parse_odds import load_aliases, price_rows
from elsim.ingest.parse_pbp import flatten
from elsim.ingest.parse_shots import field_goals
from elsim.ingest.validate import mismatches
from elsim.players.absences import load_absences

# column name -> box score field, shared by team and player rows
STATS = {
    "points": "Points",
    "fgm2": "FieldGoalsMade2",
    "fga2": "FieldGoalsAttempted2",
    "fgm3": "FieldGoalsMade3",
    "fga3": "FieldGoalsAttempted3",
    "ftm": "FreeThrowsMade",
    "fta": "FreeThrowsAttempted",
    "oreb": "OffensiveRebounds",
    "dreb": "DefensiveRebounds",
    "ast": "Assistances",
    "stl": "Steals",
    "tov": "Turnovers",
    "blk": "BlocksFavour",
    "blk_against": "BlocksAgainst",
    "fouls": "FoulsCommited",
    "fouls_drawn": "FoulsReceived",
    "valuation": "Valuation",
}
STAT_DDL = ", ".join(f"{column} INTEGER" for column in STATS)

TABLES = {
    "games": """season_code VARCHAR, game_code INTEGER, round INTEGER, phase VARCHAR,
        tipoff_utc TIMESTAMP, home_code VARCHAR, away_code VARCHAR,
        home_score INTEGER, away_score INTEGER, played BOOLEAN, status VARCHAR,
        home_standings_score INTEGER, away_standings_score INTEGER, venue_code VARCHAR,
        venue_capacity INTEGER, audience INTEGER, referee_codes VARCHAR""",
    "teams": "season_code VARCHAR, team_code VARCHAR, name VARCHAR",
    "box_team": f"""season_code VARCHAR, game_code INTEGER, team_code VARCHAR, is_home BOOLEAN,
        coach VARCHAR, {STAT_DDL}""",
    "box_player": f"""season_code VARCHAR, game_code INTEGER, player_id VARCHAR, team_code VARCHAR,
        player_name VARCHAR, is_starter BOOLEAN, did_not_play BOOLEAN, seconds INTEGER,
        plus_minus INTEGER, {STAT_DDL}""",
    "pbp_events": """season_code VARCHAR, game_code INTEGER, play_number INTEGER, period INTEGER,
        clock_seconds INTEGER, elapsed_seconds INTEGER, team_code VARCHAR, player_id VARCHAR,
        play_type VARCHAR, points_home INTEGER, points_away INTEGER""",
    "lineup_stints": """season_code VARCHAR, game_code INTEGER, stint_number INTEGER,
        team_code VARCHAR, player_ids VARCHAR, start_second INTEGER, end_second INTEGER,
        points_for INTEGER, points_against INTEGER, five_check_passed BOOLEAN""",
    "possessions": """season_code VARCHAR, game_code INTEGER, possession_number INTEGER,
        team_code VARCHAR, period INTEGER, start_second INTEGER, end_second INTEGER, points INTEGER""",
    # Everyone registered with a club in a season; type J is a player, E the head coach.
    "people": """season_code VARCHAR, team_code VARCHAR, player_id VARCHAR, name VARCHAR,
        type VARCHAR, position VARCHAR, start_date TIMESTAMP, end_date TIMESTAMP,
        birth_date TIMESTAMP, height INTEGER""",
    # Field-goal attempts with position. Filled only when the shot module is on.
    "shots": """season_code VARCHAR, game_code INTEGER, shot_number INTEGER, team_code VARCHAR,
        player_id VARCHAR, made BOOLEAN, value INTEGER, x INTEGER, y INTEGER, zone VARCHAR,
        fastbreak BOOLEAN, second_chance BOOLEAN, off_turnover BOOLEAN""",
    "odds_snapshots": """snapshot_utc TIMESTAMP, season_code VARCHAR, game_code INTEGER,
        bookmaker VARCHAR, home_price DOUBLE, away_price DOUBLE""",
    # One row per played game: what we have and whether it can be trusted.
    "game_checks": """season_code VARCHAR, game_code INTEGER, has_data BOOLEAN,
        overtime_periods INTEGER, totals_mismatch VARCHAR, five_check_passed BOOLEAN,
        bad_five_checks INTEGER, bad_substitutions INTEGER, off_court_events INTEGER,
        shots_match BOOLEAN""",
}


def _seconds(minutes: str) -> int | None:
    if not minutes or ":" not in minutes:
        return None
    whole, seconds = minutes.split(":")
    return int(whole) * 60 + int(seconds)


def _game_rows(season: str, game: dict, raw_dir: Path, rows: dict, with_shots: bool) -> None:
    code = game["gameCode"]
    key = [season, code]
    home, away = game["local"]["club"]["code"], game["road"]["club"]["code"]
    rows["games"].append(
        key
        + [
            game["round"],
            game["phaseType"]["code"],
            game["utcDate"],
            home,
            away,
            game["local"]["score"],
            game["road"]["score"],
            game["played"],
            game["gameStatus"],
            # The score that counts for the standings: points from overtime are left out.
            game["local"]["standingsScore"],
            game["road"]["standingsScore"],
            (game.get("venue") or {}).get("code"),
            (game.get("venue") or {}).get("capacity") or None,
            # Attendance is known only after the game; zero means not reported.
            game.get("audience") or None,
            # The referees, as "|"-joined codes; empty until the league assigns them.
            "|".join(r["code"] for r in (game.get(f"referee{i}") for i in (1, 2, 3, 4)) if r) or None,
        ]
    )
    if not game["played"]:
        return

    box_path = raw_dir / "boxscore" / season / f"{code}.json"
    plays_path = raw_dir / "playbyplay" / season / f"{code}.json"
    if not (box_path.exists() and plays_path.exists()):
        raise FileNotFoundError(f"{season} game {code} is played but not fetched. Run fetch-all first.")
    box = json.loads(box_path.read_text(encoding="utf-8"))
    plays = json.loads(plays_path.read_text(encoding="utf-8"))

    # The source returns an empty shell for a few games. They stay missing.
    if not box.get("Stats") or not all(team["PlayersStats"] for team in box["Stats"]):
        rows["game_checks"].append(key + [False, None, None, None, None, None, None, None])
        return

    events = flatten(plays)
    wrong = []
    for team in box["Stats"]:
        team_code = team["PlayersStats"][0]["Team"].strip()
        wrong += [f"{team_code}:{field}" for field in mismatches(team_code, team["totr"], events)]
        rows["box_team"].append(
            key + [team_code, team_code == home, team["Coach"]] + [team["totr"][field] for field in STATS.values()]
        )
        for player in team["PlayersStats"]:
            rows["box_player"].append(
                key
                + [
                    player["Player_ID"].strip(),
                    team_code,
                    player["Player"],
                    player["IsStarter"] == 1,
                    player["Minutes"] == "DNP",
                    _seconds(player["Minutes"]),
                    player["Plusminus"],
                ]
                + [player[field] for field in STATS.values()]
            )

    for event in events:
        rows["pbp_events"].append(
            key
            + [
                event["play_number"],
                event["period"],
                event["clock_seconds"],
                event["elapsed_seconds"],
                event["team_code"],
                event["player_id"],
                event["play_type"],
                event["points_home"],
                event["points_away"],
            ]
        )

    for possession in split(events):
        rows["possessions"].append(key + list(possession.values()))

    stints, report = rebuild(box, plays)
    for stint in stints:
        rows["lineup_stints"].append(
            key
            + [
                stint["stint_number"],
                stint["team_code"],
                "|".join(stint["players"]),
                stint["start_second"],
                stint["end_second"],
                stint["points_for"],
                stint["points_against"],
                stint["five_check_passed"],
            ]
        )
    # Shots: kept only when the file exists, and checked against the box
    # score. shots_match is NULL when the module is off or the file is missing.
    shots_match = None
    shots_path = raw_dir / "shots" / season / f"{code}.json"
    if with_shots and shots_path.exists():
        attempts = field_goals(json.loads(shots_path.read_text(encoding="utf-8")))
        counted = {}
        for shot in attempts:
            rows["shots"].append(key + list(shot.values()))
            tally = counted.setdefault(shot["team_code"], [0, 0, 0, 0])
            tally[(shot["value"] - 2) * 2 + (0 if shot["made"] else 1)] += 1
        shots_match = all(
            counted.get(team["PlayersStats"][0]["Team"].strip())
            == [
                team["totr"]["FieldGoalsMade2"],
                team["totr"]["FieldGoalsAttempted2"] - team["totr"]["FieldGoalsMade2"],
                team["totr"]["FieldGoalsMade3"],
                team["totr"]["FieldGoalsAttempted3"] - team["totr"]["FieldGoalsMade3"],
            ]
            for team in box["Stats"]
        )

    five_ok = report["bad_five_checks"] == 0 and report["bad_substitutions"] == 0
    rows["game_checks"].append(
        key
        + [
            True,
            max(events[-1]["period"] - 4, 0),
            ",".join(wrong),
            five_ok,
            report["bad_five_checks"],
            report["bad_substitutions"],
            report["off_court_events"],
            shots_match,
        ]
    )


def load(settings: dict) -> None:
    raw_dir = Path(settings["raw_dir"])
    db_path = Path(settings["db_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    seasons = settings["past_seasons"] + [settings["current_season"]]

    with tempfile.TemporaryDirectory() as temporary, duckdb.connect(str(db_path)) as db:
        for table, columns in TABLES.items():
            db.execute(f"CREATE OR REPLACE TABLE {table} ({columns})")
        for season in seasons:
            rows = {table: [] for table in TABLES}
            schedule = json.loads((raw_dir / "schedule" / f"{season}.json").read_text(encoding="utf-8"))
            for game in schedule["data"]:
                _game_rows(season, game, raw_dir, rows, settings["enable_shot_data"])
            clubs = {
                game[side]["club"]["code"]: game[side]["club"]["name"]
                for game in schedule["data"]
                for side in ("local", "road")
            }
            rows["teams"] = [[season, code, name] for code, name in sorted(clubs.items())]
            for people_path in sorted((raw_dir / "people" / season).glob("*.json")):
                for entry in json.loads(people_path.read_text(encoding="utf-8")):
                    person = entry["person"]
                    rows["people"].append(
                        [
                            season,
                            people_path.stem,
                            "P" + person["code"],
                            person["name"],
                            entry["type"],
                            entry.get("positionName"),
                            entry["startDate"],
                            entry["endDate"],
                            person.get("birthDate"),
                            person.get("height"),
                        ]
                    )
            if season == settings["current_season"]:
                aliases = load_aliases("odds_api")
                for odds_path in sorted((raw_dir / "odds").glob("*.json")):
                    snapshot = json.loads(odds_path.read_text(encoding="utf-8"))
                    for row in price_rows(snapshot, aliases, schedule["data"]):
                        rows["odds_snapshots"].append([row[0], season] + row[1:])
            for table, table_rows in rows.items():
                if not table_rows:
                    continue  # an empty file cannot be read back
                csv_path = Path(temporary) / f"{table}.csv"
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(table_rows)
                db.execute(
                    f"COPY {table} FROM '{csv_path.as_posix()}' (HEADER false, DELIMITER ',', QUOTE '\"', NULLSTR '')"
                )
            print(f"{season}: loaded {len(rows['games'])} games", flush=True)
        build_team_game_stats(db)
        build_features_team(db)
        build_game_context(db, load_venues(), settings.get("require_all_venues", True))
        current = settings["current_season"]
        build_roster_strength(
            db, current, load_absences(db, current, settings.get("absences_file", "config/absences.csv"))
        )
        build_player_prior(db)
        build_features_player(db)
        build_factor_inputs(db)
        build_advanced(db)
        print(
            "built team_game_stats, features_team, game_context, roster_by_game, season_start, features_player "
            "factor_inputs, player_advanced and team_advanced",
            flush=True,
        )
        if settings["enable_shot_data"]:
            build_zone_tables(db)
            games, missing = db.execute(
                """SELECT count(*) FILTER (shots_match IS NOT NULL), count(*) FILTER (shots_match IS NULL AND has_data)
                   FROM game_checks"""
            ).fetchone()
            wrong = db.execute("SELECT count(*) FROM game_checks WHERE shots_match = false").fetchone()[0]
            print(
                f"shot module on: {games} games with shots, {missing} without a shot file, "
                f"{wrong} where shots disagree with the box score",
                flush=True,
            )
        else:
            # Leave nothing behind from an earlier load with the module on.
            db.execute("DROP TABLE IF EXISTS zone_player_season")
            db.execute("DROP TABLE IF EXISTS zone_team_allowed_season")
