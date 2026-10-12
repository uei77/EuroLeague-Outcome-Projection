"""Command line entry point. Run from the project root: python -m elsim.cli --help"""

import argparse
from pathlib import Path

from elsim import settings as settings_module
from elsim.ingest.boxscore import fetch_boxscore
from elsim.ingest.playbyplay import fetch_playbyplay
from elsim.ingest.schedule import fetch_schedule
from elsim.ingest.season import fetch_season

# What "round" runs, in order. The odds snapshot is added on request.
ROUND_CYCLE = ["fetch-all", "fetch-people", "load", "track-record", "predict", "simulate"]


def execute(args, settings: dict) -> None:
    """Run one command."""
    if args.command == "fetch-schedule":
        games = fetch_schedule(args.season, settings)
        print(f"schedule {args.season}: {len(games)} games, {sum(g['played'] for g in games)} played")
    elif args.command == "fetch-games":
        for game_code in range(args.first, args.last + 1):
            box = fetch_boxscore(args.season, game_code, settings)
            plays = fetch_playbyplay(args.season, game_code, settings)
            print(f"{args.season} game {game_code}: box score {len(box)} bytes, play-by-play {len(plays)} bytes")
    elif args.command in ("fetch-season", "fetch-all"):
        seasons = (
            [args.season] if args.command == "fetch-season" else settings["past_seasons"] + [settings["current_season"]]
        )
        failures = {}
        for season_code in seasons:
            failures[season_code] = fetch_season(season_code, settings)
        for season_code, failed in failures.items():
            print(f"{season_code}: {len(failed)} failed games {[code for code, _ in failed]}")
    elif args.command == "fetch-people":
        from elsim.ingest.people import fetch_people

        for season_code in settings["past_seasons"] + [settings["current_season"]]:
            print(f"{season_code}: {fetch_people(season_code, settings)} clubs", flush=True)
    elif args.command == "snapshot-odds":
        import json

        from elsim.ingest.odds import take_snapshot

        path = take_snapshot(settings)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        print(
            f"saved {path}: {len(snapshot['events'])} games, "
            f"{snapshot['credits_used_by_this_request']} credit used, {snapshot['credits_remaining']} remaining"
        )
    elif args.command == "load":
        from elsim.ingest.load_raw import load  # imported here so fetching needs no installed packages

        load(settings)
    elif args.command == "backtest":
        import duckdb

        from elsim.models import elo
        from elsim.models.backtest import RATING_MODELS, STAGE_TWO_MODELS, load_games, summary, walk_forward
        from elsim.models.compare import compare

        with duckdb.connect(settings["db_path"], read_only=True) as db:
            rows, fitted = walk_forward(db, settings["first_test_season"], settings["seed"])
            all_rows = load_games(db)[0]
        for r in all_rows:
            r["margin"] = r["home_per_100"] - r["away_per_100"]
        elo_p, _ = elo.walk_forward(all_rows, settings["first_test_season"])
        by_game = {(r["season_code"], r["game_code"]): p for r, p in zip(all_rows, elo_p)}
        for r in rows:
            r["p_elo"] = by_game[(r["season_code"], r["game_code"])]
        for models in (["p_elo"] + RATING_MODELS, STAGE_TWO_MODELS):
            print(
                f"\n{'games':>12} {'n':>5} "
                + " ".join(f"{m[2:]:>10}" for m in models)
                + "   (log loss, lower is better)"
            )
            for name, n, *losses in summary(rows, models):
                print(f"{name:>12} {n:>5} " + " ".join(f"{v:>10.4f}" for v in losses))
        from elsim.models.score import evaluate

        scores = evaluate(rows)
        print(
            f"\nexpected scores on {scores['games']} games: mean absolute error, model against "
            "every earlier season's average score"
        )
        for part in ("home", "away", "total", "margin"):
            print(f"  {part:<7} {scores[part][0]:>5.1f} points   (average score {scores[part][1]:>5.1f})")
        print(
            f"  80% intervals held the real margin in {scores['margin_80']:.0%} and the total in {scores['total_80']:.0%} of games"
        )
        print("\npublished model against, resampling whole rounds (negative = published better):")
        for other in ("p_elo", "p_rating"):
            c = compare(rows, other, "p_roster")
            print(
                f"  vs {other[2:]:<7} {c['mean']:+.4f}, 90% interval {c['low']:+.4f} to {c['high']:+.4f}, "
                f"better in {c['p_better']:.0%} of resamples and {c['seasons_better']} of {c['seasons']} seasons"
            )
        # Keep each season's fitted settings, so the other backtests can reuse them.
        import json

        with duckdb.connect(settings["db_path"]) as db:
            db.execute("CREATE OR REPLACE TABLE backtest_settings (season_code VARCHAR, parameters VARCHAR)")
            for season_code, fitted_models in fitted.items():
                db.execute(
                    "INSERT INTO backtest_settings VALUES (?, ?)",
                    [season_code, json.dumps(fitted_models["p_roster"]._asdict())],
                )
        from elsim.models.calibration import plot, save_confidence, table

        print("\ncalibration of the rating model with roster start")
        print(f"{'forecast':>11} {'n':>5} {'mean':>6} {'actual':>7} {'95% interval':>14}")
        for low, high, n, mean, actual, lo, hi in table(rows, "p_roster"):
            print(f"{low:>5.0%}-{high:<5.0%} {n:>5} {mean:>6.3f} {actual:>7.3f}   {lo:.3f}-{hi:.3f}")
        reports = Path(settings.get("reports_dir", "reports"))
        reports.mkdir(parents=True, exist_ok=True)
        plot(rows, str(reports / "calibration.png"))
        save_confidence(rows, "p_roster", str(reports / "confidence.csv"))
        print(f"accuracy on confident forecasts saved to {reports / 'confidence.csv'}")
        print(f"chart saved to {reports / 'calibration.png'}")
    elif args.command == "simulate":
        import duckdb

        from elsim.simulate.season import simulate_season

        with duckdb.connect(settings["db_path"]) as db:
            run_id, results = simulate_season(db, settings)
        for scenario, result in results.items():
            label = {"baseline": "without known absences", "with_absences": "with known absences (hand-entered)"}[
                scenario
            ]
            print(
                f"\nrun {run_id}, {label}: {result['n_paths']:,} paths, seed {settings['seed']}, "
                f"{result['random_ties']} ties broken at random"
            )
            print(f"{'team':<5} {'wins':>5} {'play-in':>8} {'playoffs':>9} {'Final Four':>11} {'title':>7}")
            for i in sorted(range(len(result["teams"])), key=lambda i: -result["expected_wins"][i]):
                print(
                    f"{result['teams'][i]:<5} {result['expected_wins'][i]:>5.1f} {result['play_in'][i]:>8.1%} "
                    f"{result['playoffs'][i]:>9.1%} {result['final_four'][i]:>11.1%} {result['title'][i]:>7.1%}"
                )
            print(
                f"sums: play-in {result['play_in'].sum():.4f}, playoffs {result['playoffs'].sum():.4f}, "
                f"Final Four {result['final_four'].sum():.4f}, title {result['title'].sum():.4f}"
            )
    elif args.command == "publish":
        import subprocess

        folders = sorted(
            (Path(settings.get("forecasts_dir", "forecasts")) / settings["current_season"]).glob("round-*"),
            key=lambda f: f.stat().st_mtime,
        )
        if not folders:
            raise SystemExit("No forecast files yet: run predict first.")
        folder = folders[-1]
        rounds = [int(n) for n in folder.name.split("-")[1:]]
        git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True)
        git("add", str(folder))
        if not git("diff", "--cached", "--quiet", "--", str(folder)).returncode:
            print(f"{folder}: nothing new to publish")
        else:
            message = f"Matchweek update: round{'s' if len(rounds) > 1 else ''} {' and '.join(map(str, rounds))}"
            commit = git("commit", "-m", message, "--", str(folder))
            if commit.returncode:
                raise SystemExit(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")
            push = git("push")
            if push.returncode:
                raise SystemExit(f"Committed '{message}' but git push failed: {push.stderr.strip()}")
            print(f"published {folder}: '{message}'")
    elif args.command == "odds-plan":
        from datetime import timedelta, timezone

        import duckdb

        with duckdb.connect(settings["db_path"], read_only=True) as db:
            days = db.execute(
                """SELECT round, tipoff_utc::DATE AS day, min(tipoff_utc), count(*) FROM games
                   WHERE season_code = ? AND NOT played AND status <> 'Cancelled' AND tipoff_utc > now()::TIMESTAMP
                   GROUP BY ALL ORDER BY 3 LIMIT 6""",
                [settings["current_season"]],
            ).fetchall()
        local = lambda t: t.replace(tzinfo=timezone.utc).astimezone()
        print("Odds snapshots for the coming match days (one credit each). Times are this computer's local time.")
        for round_number, _, first, n in days:
            closing = local(first - timedelta(minutes=45))
            print(
                f"  round {round_number:>2}: {n} games, first tip-off {local(first):%a %d %b %H:%M}"
                f" -> snapshot-odds between {local(first - timedelta(minutes=60)):%H:%M} and {local(first - timedelta(minutes=10)):%H:%M}"
                f" (aim for {closing:%H:%M})"
            )
        print("The opening snapshot is the one `round --odds` takes the day before a round.")
    elif args.command == "track-record":
        import duckdb

        from elsim.api import queries
        from elsim.models.market import closing_line_value, summarise

        with duckdb.connect(settings["db_path"], read_only=True) as db:
            tables = {t[0] for t in db.execute("SELECT table_name FROM information_schema.tables").fetchall()}
            rows = (
                queries.track_record(db, settings["current_season"])
                if {"game_predictions", "model_runs"} <= tables
                else []
            )
        if not rows:
            print("No finished game yet had both a stored forecast and an odds snapshot from before its tip-off.")
        else:
            print("log loss, lower is better; forecast and odds both from before tip-off")
            print(f"{'round':>6} {'games':>6} {'model':>8} {'with absences':>14} {'market':>8}")
            for line in summarise(rows):
                print(
                    f"{line['round']:>6} {line['games']:>6} {line['model']:>8.4f} "
                    f"{line['model_with_absences']:>14.4f} {line['market']:>8.4f}"
                )
            clv = closing_line_value(rows)
            if clv:
                print(
                    f"closing-line value over {clv['moving']} games whose price moved between two snapshots: "
                    f"{clv['share_toward_us']:.0%} moved towards our forecast, "
                    f"average move {100 * clv['average_move_toward_us']:+.2f} points our way (50% and 0 = no edge)"
                )
            print("A handful of games says little: the difference only means something over many rounds.")
    elif args.command in ("backtest-simulator", "backtest-absences"):
        import json

        import duckdb

        from elsim.models.predict import load_inputs
        from elsim.models.state_space import Params

        with duckdb.connect(settings["db_path"], read_only=True) as db:
            tables = {t[0] for t in db.execute("SELECT table_name FROM information_schema.tables").fetchall()}
            if "backtest_settings" not in tables:
                raise SystemExit(
                    "Run 'python -m elsim.cli backtest' first: it stores the settings fitted for each season."
                )
            by_season = {
                s: Params(**json.loads(p)) for s, p in db.execute("SELECT * FROM backtest_settings").fetchall()
            }
            rows, games, season_start = load_inputs(db, settings["current_season"])
            if args.command == "backtest-absences":
                from elsim.players.breakout import load_candidates

                flat = {
                    (r["season_code"], r["game_code"], t): 80.0 for r in rows for t in (r["home_code"], r["away_code"])
                }
                candidates = load_candidates(db, flat)  # the parts used here do not depend on expected points
        mean = lambda values: sum(values) / len(values)
        if args.command == "backtest-simulator":
            from elsim.simulate.backtest import CHECKPOINTS, SKIPPED_SEASONS, calibration, season_checkpoint, summarise
            from elsim.simulate.season import load_format

            config, records = load_format(settings), []
            for season_code in sorted(by_season):
                if season_code in SKIPPED_SEASONS or season_code == settings["current_season"]:
                    continue
                for checkpoint in CHECKPOINTS:
                    records += season_checkpoint(
                        rows,
                        games,
                        season_start,
                        by_season[season_code],
                        season_code,
                        checkpoint,
                        config,
                        20000,
                        settings["seed"],
                    )
                print(f"{season_code}: simulated from rounds {CHECKPOINTS}", flush=True)
            print(
                f"\n{'after round':>11} {'team-seasons':>12} {'Brier top 8':>12} {'no skill':>9} {'wins error':>11} "
                f"{'in 50%':>7} {'in 80%':>7} {'in 95%':>7}"
            )
            for line in summarise(records):
                print(
                    f"{line['after_round']:>11} {line['team_seasons']:>12} {line['brier_top8']:>12.3f} "
                    f"{line['brier_top8_no_skill']:>9.3f} {line['wins_error']:>11.2f} {line['inside_50']:>7.0%} "
                    f"{line['inside_80']:>7.0%} {line['inside_95']:>7.0%}"
                )
            print("in 50% / 80% / 95%: how often the real win total fell inside the simulated interval of that size")
            print("\nstated chance of a top-eight finish against what happened")
            print(f"{'stated':>11} {'team-seasons':>12} {'mean stated':>12} {'happened':>9}")
            for low, high, n, stated, happened in calibration(records):
                print(f"{low:>5.0%}-{high:<5.0%} {n:>12} {stated:>12.3f} {happened:>9.3f}")
        else:
            from elsim.models.absence_backtest import FRESH_GAMES, STAR_LEVEL, run_backtest

            all_games, star_games = run_backtest(rows, games, season_start, by_season, candidates)
            print(f"{len(all_games)} games; log loss, lower is better")
            print(f"{'season':>8} {'games':>6} {'model':>8} {'absences known':>15}")
            for season_code in sorted({g["season"] for g in all_games}) + ["all"]:
                group = [g for g in all_games if season_code in ("all", g["season"])]
                print(
                    f"{season_code:>8} {len(group):>6} {mean([g['model'] for g in group]):>8.4f} "
                    f"{mean([g['informed'] for g in group]):>15.4f}"
                )
            print(
                f"\ngames where one team alone missed a star (level {STAR_LEVEL:.0f} or more) in his first "
                f"{FRESH_GAMES} games out: {len(star_games)}"
            )
            print(
                f"model's mean win chance for that team {mean([g['p_weakened'] for g in star_games]):.3f}, "
                f"it won {mean([g['weakened_won'] for g in star_games]):.3f} of them"
            )
            misses = [g["margin_miss"] for g in star_games]
            spread = (sum((m - mean(misses)) ** 2 for m in misses) / len(misses)) ** 0.5 / len(misses) ** 0.5
            print(
                f"its margin against the forecast: {mean(misses):+.2f} points per 100 possessions (standard error {spread:.2f})"
            )
    elif args.command == "backtest-players":
        import json

        import duckdb

        from elsim.models.predict import load_inputs
        from elsim.models.state_space import Params, run
        from elsim.players.breakout import load_candidates
        from elsim.players.evaluate import LISTS, walk_forward

        with duckdb.connect(settings["db_path"], read_only=True) as db:
            parameters = db.execute("SELECT parameters FROM model_runs ORDER BY created_utc DESC LIMIT 1").fetchone()[0]
            rows, games, season_start = load_inputs(db, settings["current_season"])
            league_pace = sum(r["pace"] for r in rows if r["pace"]) / sum(1 for r in rows if r["pace"])
            expected_points = {}
            for row, prediction in zip(rows, run(games, Params(**json.loads(parameters)["settings"]), season_start)):
                possessions = (row["pace"] or league_pace) / 100.0
                expected_points[(row["season_code"], row["game_code"], row["home_code"])] = (
                    prediction.home_per_100 * possessions
                )
                expected_points[(row["season_code"], row["game_code"], row["away_code"])] = (
                    prediction.away_per_100 * possessions
                )
            records, _ = walk_forward(load_candidates(db, expected_points))
        mean = lambda values: sum(values) / len(values)
        top = [r for r in records if r["list"] != "rising"]
        print(
            f"{len(top) // len(LISTS)} past rounds; ten players per list; a listed player who did not play counts as zero"
        )
        print(f"{'list':<18} {'valuation':>9} {'points':>7} {'assists':>8} {'played':>7}")
        for name in LISTS:
            group = [r for r in top if r["list"] == name]
            print(
                f"{name:<18} {mean([r['valuation'] for r in group]):>9.2f} {mean([r['points'] for r in group]):>7.2f} "
                f"{mean([r['assists'] for r in group]):>8.2f} {mean([r['played'] for r in group]):>7.0%}"
            )
        print(f"{'all starters':<18} {mean([r['starters_valuation'] for r in top]):>9.2f}")
        rising = [r for r in records if r["list"] == "rising"]
        print("\n'rising' list: valuation above the player's own season average")
        print(f"{'':<24} {'listed':>7} {'all rotation':>13}")
        for label, a, b in (
            ("counting absences as 0", "picked_over_own_average", "rotation_over_own_average"),
            ("share who played", "picked_played", "rotation_played"),
            ("only when they played", "picked_over_when_played", "rotation_over_when_played"),
        ):
            print(f"{label:<24} {mean([r[a] for r in rising]):>7.2f} {mean([r[b] for r in rising]):>13.2f}")
    elif args.command == "predict":
        import duckdb

        from elsim.features.factors import FACTORS
        from elsim.features.roster import build_roster_strength
        from elsim.models.explain import explain
        from elsim.models.predict import MARKET_SQL, predict_upcoming, store, store_postseason_shifts
        from elsim.players.absences import load_absences, mark_absent, store_absences
        from elsim.players.breakout import load_candidates, players_to_watch

        season = settings["current_season"]
        with duckdb.connect(settings["db_path"]) as db:
            absent = load_absences(db, season, settings.get("absences_file", "config/absences.csv"))
            build_roster_strength(db, season, absent)  # so edits to config/absences.csv count without a new load
            result = predict_upcoming(db, settings)
            run_id, rows = result["run_id"], result["upcoming"]
            candidates = load_candidates(db, result["expected_points"])
            mark_absent(candidates, absent, curve=[0.0])  # only to leave absent players off the lists
            store(db, run_id, rows)
            store_postseason_shifts(db, run_id, result["postseason_shift"])
            effects = explain(db, run_id, result)
            store_absences(db, run_id, absent)
            watch = players_to_watch(db, run_id, season, candidates)
            market = {g: (p, n) for g, p, n in db.execute(MARKET_SQL, [season]).fetchall()}
            names = dict(
                db.execute("SELECT DISTINCT player_id, name FROM people WHERE season_code = ?", [season]).fetchall()
            )
            teams = dict(db.execute("SELECT team_code, name FROM teams WHERE season_code = ?", [season]).fetchall())
        from elsim.report import matchweek, week_label, write_reports

        week = matchweek(rows)
        write_reports(
            Path(settings.get("forecasts_dir", "forecasts")) / season / week_label(week),
            run_id,
            [r for r in rows if r["round"] in week],
            candidates,
            market,
            teams,
            [f"{names[p]} until {d:%Y-%m-%d}" for p, d in absent.items()],
            week,
            {(r["player_id"], r["game_code"]) for lists in watch.values() for r in lists["rising"]},
        )
        games_file, players_file = write_reports(
            Path(settings.get("predictions_dir", "predictions")) / run_id,
            run_id,
            rows,
            candidates,
            market,
            teams,
            [f"{names[p]} until {d:%Y-%m-%d}" for p, d in absent.items()],
            sorted(watch),
            {(r["player_id"], r["game_code"]) for lists in watch.values() for r in lists["rising"]},
        )
        next_rounds = sorted({r["round"] for r in rows})[:2]
        print(f"run {run_id}: {len(rows)} unplayed games forecast; showing rounds {next_rounds}")
        print(
            f"known absences ({len(absent)}): "
            + ("; ".join(f"{names[p]} until {d:%Y-%m-%d}" for p, d in absent.items()) or "none")
        )
        print(
            "Each team is valued by the registered players expected to be available (played in one of its last three "
            'games, or newly registered); "with absences" also leaves out the players above.'
        )
        print(
            f"{'tip-off (UTC)':<17} {'home':<5}{'away':<5} {'P(home)':>8} {'score':>9} {'margin':>7} {'with absences':>14} {'market':>7} {'books':>5}"
        )
        for r in rows:
            if r["round"] in next_rounds:
                p_market, books = market.get(r["game_code"], (None, 0))
                shown = f"{p_market:>7.3f}" if p_market is not None else f"{'-':>7}"
                adjusted = f"{r['p_home_with_absences']:>14.3f}" if r["absence_shift"] else f"{'':>14}"
                print(
                    f"{r['tipoff_utc']:%Y-%m-%d %H:%M}  {r['home_code']:<5}{r['away_code']:<5} "
                    f"{r['p_home']:>8.3f} {r['home_points']:>4.0f}-{r['away_points']:<4.0f} {r['expected_margin']:>+7.1f} "
                    f"{adjusted} {shown} {books:>5}"
                )
        print(
            "\nNot in the forecast (tried, no gain). What a typical difference between two teams has been worth "
            "beyond the forecast, points per 100 possessions:"
        )
        for name, (effect, se, count, spread) in effects.items():
            print(f"  {name:<11} {effect * spread:>+6.2f} ± {se * spread:.2f}  ({FACTORS[name][0]}; {count} games)")
        round_number = min(watch)
        titles = {
            "top": "expected to produce most (no better than season averages on past rounds)",
            "rising": "expected to beat their own norm (rotation players)",
        }
        for which, title in titles.items():
            print(f"\nPlayers to Watch, round {round_number}: {title}")
            print(
                f"{'':>2} {'player':<26}{'team':<5}{'v':<5}{'pos':<8} {'score':>6} {'lift':>6} | "
                f"{'level':>6} {'minutes':>7} {'rate':>6} {'matchup':>7} {'team':>6}"
            )
            for rank, r in enumerate(watch[round_number][which], start=1):
                w = r["weighted"]
                print(
                    f"{rank:>2} {r['player_name'][:25]:<26}{r['team_code']:<5}{r['opponent_code']:<5}{r['position']:<8} "
                    f"{r['score']:>6.1f} {r['lift']:>+6.1f} | {w['level']:>6.1f} {w['minutes_form']:>+7.1f} "
                    f"{w['rate_form']:>+6.1f} {w['matchup']:>+7.1f} {w['team']:>+6.1f}"
                )
        print("Matchup is by position (guard, forward, center). Availability is unknown: a listed player may not play.")
        print(f"\ngame-by-game forecasts written to {games_file}\nplayer forecasts written to {players_file}")
        print(
            f"this matchweek's files (rounds {', '.join(map(str, week))}) written to "
            f"{Path(settings.get('forecasts_dir', 'forecasts')) / season / week_label(week)}; `publish` sends them to GitHub"
        )
        if round_number <= 6:
            print("Early season: on past seasons the second list showed no edge in rounds 1 to 6.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="elsim")
    commands = parser.add_subparsers(dest="command", required=True)

    schedule = commands.add_parser("fetch-schedule", help="save one season's game list")
    schedule.add_argument("season", help="for example E2026")

    games = commands.add_parser("fetch-games", help="save box score and play-by-play for a range of game codes")
    games.add_argument("season", help="for example E2026")
    games.add_argument("first", type=int)
    games.add_argument("last", type=int)

    season = commands.add_parser("fetch-season", help="save every played game of one season")
    season.add_argument("season", help="for example E2026")

    commands.add_parser("fetch-all", help="save every played game of all configured seasons")

    commands.add_parser("fetch-people", help="save every club's registered players and coaches, all seasons")
    commands.add_parser("snapshot-odds", help="save current pre-game odds (costs one credit)")
    commands.add_parser("load", help="rebuild the database from the raw files")

    round_parser = commands.add_parser("round", help="the whole round cycle: fetch, load, predict, simulate")
    round_parser.add_argument("--odds", action="store_true", help="also take an odds snapshot (costs one credit)")
    round_parser.add_argument(
        "--publish", action="store_true", help="finally commit and push this matchweek's forecasts"
    )
    commands.add_parser("predict", help="forecast the unplayed games and store them under a run id")
    commands.add_parser("simulate", help="simulate the rest of the season for the latest model run")
    commands.add_parser("track-record", help="our forecasts against the market on finished games")
    commands.add_parser("backtest-players", help="check Players to Watch on past rounds (run predict first)")
    commands.add_parser("backtest-simulator", help="check the season simulator on past seasons (run backtest first)")
    commands.add_parser("backtest-absences", help="how much could knowing absences help (run backtest first)")
    commands.add_parser("backtest", help="walk-forward backtest of the game models")
    commands.add_parser("publish", help="commit and push this matchweek's forecast files to GitHub")
    commands.add_parser("odds-plan", help="when to take the closing odds snapshots for the coming match days")

    args = parser.parse_args()
    settings = settings_module.load()

    if args.command == "round":
        steps = ROUND_CYCLE[:2] + (["snapshot-odds"] if args.odds else []) + ROUND_CYCLE[2:]
        steps += ["publish"] if args.publish else []
        for step in steps:
            print(f"\n=== {step} ===", flush=True)
            execute(argparse.Namespace(command=step), settings)
    else:
        execute(args, settings)


if __name__ == "__main__":
    main()
