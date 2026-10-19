# EuroLeague prediction and simulation platform: plan

Status: approved on 10 October 2026, including changes 1 to 9 below. No code has been written yet.

## Goal

Each round, answer three questions for the 2026-27 EuroLeague season from stored data and a recorded model run: each team's win probability in every upcoming game, which players are most likely to stand out, and each team's chances of the title, the Final Four, the playoffs and the play-in.

## How I read your decisions

You replied "tamam, planı başlatalım" to a message that listed three open decisions. I have taken that as yes to all three. Correct me if any of them is wrong, because each one shapes the build.

1. Proceed although no terms of use were found for the league API (assumption 3).
2. Accept `live.euroleague.net` as the source for box score and play-by-play.
3. Load eight past seasons, E2018 to E2025, plus E2026.

You also approved replacing the time-weighted rating model with a state-space model that starts each season from a club component plus a roster component.

## Step 0 results

| # | Assumption | Result | Evidence |
|---|---|---|---|
| 1 | The API serves box score and play-by-play for 2026-27 and at least five past seasons without a key | Pass, with a host correction | Game 1 of E2021 to E2026 returned HTTP 200 for both endpoints with real scores. Single probes of E2007, E2012, E2016, E2018 and E2020 also returned both. E2003 returned an empty body. |
| 2 | Play-by-play substitutions are enough to rebuild the five on court | Pass | Ten games across E2021 to E2026: 8,352 team checks, none with other than five players; no invalid `IN` or `OUT`; points rebuilt from play-by-play equal the box score in all ten. |
| 3 | Private use of the API is acceptable | Open | No terms page was found for either API host and the Swagger document has no terms, licence or contact field. No prohibition was found. You decided to proceed. |
| 5 | The Odds API free plan covers one snapshot per round | Pass, measured | One request cost 1 credit (`x-requests-last: 1`, 499 of 500 remaining) and returned 19 games: all 10 of the 13-14 October round and 9 of 10 of the 15-16 October round. |

Findings that affect the design:

- **Two hosts.** Schedule and season data come from `api-live.euroleague.net` (versions v1 to v3). Box score and play-by-play come from `live.euroleague.net/api`. The `euroleague-api` package uses the same split.
- **A key scheme is declared.** The v3 Swagger document on `api-live` defines an API key header. Calls work without a key today; that could change.
- **League posture.** The terms of a different league site, publications.euroleague.net, prohibit download and reproduction of its content without approval. They do not cover the API hosts, but they are the nearest evidence of how the league views reuse.
- **Lineup noise.** No overtime game was in the sample. Rebuilt minutes differ from the box score by at most 29 seconds. Seven events were credited to a player who was not on court at that moment (assists, blocks, one foul, one free throw), which looks like event-ordering noise.
- **Odds coverage and names.** The game missing from the second round was the one between Fenerbahce and Partizan, not yet priced three days ahead. The Odds API uses different team names from the league ("KK Crvena zvezda", "Žalgiris", "Fenerbahce SK").
- **Where code can run.** My cloud environment cannot reach either league host. The step 0 checks ran through the browser pane of your desktop app. Ingestion has to run on your computer.

## What I would change in the brief, and why

Each of these changes what gets built. You agreed to all nine on 10 October 2026.

1. **Source host.** Box score and play-by-play are read from `live.euroleague.net/api`, as found in step 0.

2. **Stage one becomes a state-space rating model.** Each team's offensive and defensive strength is held as an estimate with an uncertainty. The uncertainty widens between seasons and narrows with each game, so early-season games of 2026-27 move the estimate strongly without a hand-set weight. The season-start estimate is a weighted sum of two parts:
   - a roster part: the value of the players on the current roster, weighted by expected minutes. In the MVP a player's value is computed from box scores only.
   - a club part: what the team achieved beyond what its roster value predicted, carried over only as far as the coach is the same (box score has a `Coach` field) and as far as style measures (pace, three-point rate, offensive rebound rate, turnover rate) are shown to persist from season to season.

   The two weights and the between-season widening are estimated by walk-forward backtest, scored on the first ten rounds of each season. A part that does not lower log loss there is removed and reported to you.

3. **Eight past seasons, not five.** Player values need more history than team ratings do. Two seasons need special handling: 2019-20 was stopped early and had no playoffs, and 2020-21 was played largely without spectators, so home advantage is estimated separately for it.

4. **Simulate the rest of the season from stage one, not from LightGBM.** The brief samples every remaining game from the 2A probabilities. LightGBM needs form, rest days and absences for each game, and those do not exist for a game in March or for a playoff pairing that is not yet known. Filling them in would be invented data. I propose that LightGBM predicts the next round only, and the simulator uses stage-one probabilities for all later games.

5. **Draw team strengths per simulation path.** If every path uses the same fixed probabilities, title and playoff chances come out too confident, because the model's own uncertainty about each team is ignored. Each of the 100,000 paths would first draw each team's strength from its current estimate and uncertainty, then play the games.

6. **Random shocks only from observed rates.** The brief asks for injury and foul-trouble shocks in each path, but there is no injury data, so the size of a shock would be a guess. I propose a separate sensitivity run in which player absences are drawn at the rates seen in past box scores ("did not play"), labelled as a sensitivity result. The headline probabilities come from the run without shocks. Foul trouble is left out, because its effect is already inside the game-to-game noise the model is fitted on.

7. **Stage two has two candidates, and each has to earn its place.** Eight seasons give roughly 2,500 games, which is small for gradient boosting. Stage two is therefore built twice on the same features: a regularised logistic regression (scikit-learn) and LightGBM with tight settings (shallow trees, few of them). The backtest reports four models side by side: constant home-win rate, stage one alone, logistic regression, LightGBM. The one with the best out-of-sample log loss is published; if the difference is within noise, the simpler model wins, and the dashboard names the model in use. Agreed on 10 October 2026.

8. **A lighter storage stack for the MVP.** The brief uses PostgreSQL for raw data, dbt, DuckDB for features, Prefect and Redis. For a per-round batch run by one person, PostgreSQL next to DuckDB means two databases to keep in step, and Redis has no native Windows build (it needs WSL or Docker). I propose that steps 1 to 3 use the raw JSON disk cache plus one DuckDB file, with dbt on DuckDB. PostgreSQL, Prefect and Redis are added at steps 5 and 6 if you still want them then. This is the one change that is about effort, not about what the predictions mean; if you prefer the full stack from the start, I will build that.

9. **A stronger baseline for the player engine.** Comparing "Players to Watch" with the league average for starters is easy to beat. I propose also comparing with the ten players who have the highest season average of the same output measure, which is what a reader would guess without a model.

## Scope

In the MVP: steps 1 to 3, on box score and play-by-play, with results printed as a table. Odds snapshots are also collected from step 1, because a round that is not snapshotted cannot be recovered later.

After the MVP, in order: player engine, player values from lineup data as a challenger to box-score values, API, dashboard, shot module.

Not doing, unchanged from the brief: player tracking and pass data; scraping other statistics sites; historical odds; live in-game predictions; betting advice; other competitions; user accounts; public hosting; Feast, Airflow, Next.js.

## Repository structure

One file, one responsibility.

```
euroleague-sim/
├── README.md                  decisions log and how to run
├── .env.example               ODDS_API_KEY and paths; no real values
├── pyproject.toml
├── config/
│   ├── settings.toml          request rate, seasons, ENABLE_SHOT_DATA, seed
│   ├── format_2026.toml       teams, rounds, play-in, playoff and Final Four rules, tie-breaks
│   └── team_aliases.csv       league team code to Odds API name, checked by hand
├── data/                      not committed
│   ├── raw/                   one JSON file per response, never fetched twice
│   └── euroleague.duckdb
├── src/elsim/
│   ├── ingest/
│   │   ├── http_cache.py      rate-limited fetch with disk cache
│   │   ├── schedule.py        seasons and games from api-live
│   │   ├── boxscore.py        box score from live host
│   │   ├── playbyplay.py      play-by-play from live host
│   │   ├── odds.py            Odds API snapshot
│   │   └── load_raw.py        raw JSON into DuckDB raw tables
│   ├── derive/
│   │   ├── lineups.py         on-court fives and stints
│   │   └── possessions.py     possession boundaries
│   ├── features/
│   │   ├── team.py            ratings per 100, pace, four factors, rest
│   │   ├── player.py          usage, true shooting, box-score value
│   │   └── asof.py            the single place that enforces "before tip-off"
│   ├── models/
│   │   ├── season_prior.py    roster part plus club part
│   │   ├── state_space.py     stage one
│   │   ├── logistic.py        stage two, candidate one
│   │   ├── gbm.py             stage two, candidate two
│   │   └── backtest.py        walk-forward, log loss, calibration
│   ├── simulate/
│   │   ├── table.py           standings and tie-breaks from config
│   │   ├── postseason.py      play-in, playoffs, Final Four
│   │   └── monte_carlo.py     100,000 paths with recorded seed
│   ├── runs.py                model_runs: run id, git SHA, parameters, seed
│   └── cli.py                 one command per step and one for the round cycle
├── dbt/                       models from raw tables to feature tables
└── tests/
    ├── fixtures/              saved real responses, including overtime games
    ├── test_lineups.py
    ├── test_pbp_equals_box.py
    ├── test_no_leakage.py
    └── test_simulator.py
```

Added after the MVP: `src/elsim/players/` (breakout score), `src/elsim/api/` (FastAPI), `dashboard/` (Streamlit), `src/elsim/ingest/shots.py` behind the flag.

## Database schema

Keys are in bold. Every table derived from a model carries `run_id`.

| Table | Columns |
|---|---|
| `seasons` | **season_code**, start_date, end_date, n_teams, n_rounds |
| `teams` | **team_code**, name |
| `team_aliases` | **team_code**, **source**, alias |
| `players` | **player_id**, name |
| `games` | **season_code**, **game_code**, round, phase, tipoff_utc, home_code, away_code, home_score, away_score, overtime_periods, played |
| `box_team` | **season_code**, **game_code**, **team_code**, coach, points, shooting, rebound, assist, steal, turnover, block and foul totals |
| `box_player` | **season_code**, **game_code**, **player_id**, team_code, is_starter, seconds, the same counting columns, did_not_play |
| `pbp_events` | **season_code**, **game_code**, **play_number**, period, clock_seconds, team_code, player_id, play_type, points_home, points_away |
| `lineup_stints` | **season_code**, **game_code**, **stint_number**, team_code, five player ids, start_second, end_second, points_for, points_against, five_check_passed |
| `possessions` | **season_code**, **game_code**, **possession_number**, team_code, start_second, end_second, points, end_type |
| `odds_snapshots` | **snapshot_utc**, **season_code**, **game_code**, **bookmaker**, home_price, away_price |
| `shots` | created only when `ENABLE_SHOT_DATA` is on |
| `features_team` | **season_code**, **game_code**, **team_code**, **asof_utc**, feature columns |
| `features_player` | **season_code**, **game_code**, **player_id**, **asof_utc**, feature columns |
| `ratings_team` | **run_id**, **team_code**, **asof_utc**, offence mean and variance, defence mean and variance, pace |
| `model_runs` | **run_id**, created_utc, git_sha, parameters as JSON, seed, data_through_utc |
| `game_predictions` | **run_id**, **season_code**, **game_code**, p_home_stage1, p_home_final, expected_margin, model_used |
| `breakout_scores` | **run_id**, **season_code**, **round**, **player_id**, form, matchup, team_points, score, matchup_basis (position or zone) |
| `sim_results` | **run_id**, **team_code**, **scenario** (baseline or absence sensitivity), p_title, p_final_four, p_playoffs, p_play_in |

Leakage rule: stage one supplies only filtered estimates, meaning the estimate as it stood before tip-off, never one revised with later games. `asof.py` is the only module allowed to join game data to features, and `test_no_leakage.py` fails if any feature row draws on a record dated at or after its game's tip-off.

## Steps

1. **Data pipeline** → done when: E2018 to E2026 are loaded; team totals rebuilt from play-by-play equal the box score for every game, with any failing game listed and excluded from lineup features; the share of games failing the five-players check is reported per season, with overtime games included; the leakage test fails on a deliberately leaked feature and passes otherwise; one odds snapshot per round is stored. Expect about 5,000 requests at one per second, roughly an hour and a half, once.
2. **Game engine** → done when: a walk-forward backtest over past seasons reports log loss and a calibration plot for four models (constant home-win rate, stage one alone, stage one plus logistic regression, stage one plus LightGBM), with a separate figure for the first ten rounds of each season, and states which model is published.
3. **Simulator** → done when: probabilities sum to 1 for the title, 4 for the Final Four and 8 for the playoffs; the same seed reproduces the same result; a team that is mathematically in or out shows 100% or 0%; the tie-break rules in the config file are quoted from the current league regulations. This completes the MVP.
4. **Player engine** → done when: for past rounds, the listed players' actual output is compared with both baselines.
5. **API** → done when: endpoints answer from the store and every response carries a run id.
6. **Dashboard** → done when: one command runs the round cycle on real data and the dashboard shows game probabilities, "Players to Watch" with the three factors, the simulation probabilities, and the note that upcoming availability is assumed from the recent rotation.
7. **Shot module**, only if you turn it on → done when: assumption 4 passes and shot charts and zone features appear, with nothing else changed when the flag is off.

From step 1 on, the odds-implied probability is logged beside ours for every snapshotted game and the running comparison is reported each round. Implied probabilities are the bookmaker average with the margin removed.

## How the work is split between us

- I write the code and run the logic tests in my environment against saved real responses in `tests/fixtures/`.
- Everything that touches the league hosts or The Odds API runs on your computer. For each step I give you the exact commands and say which output to send back.
- To do that I need a project folder on your computer connected to this chat, and Python 3.11 or newer installed there. Your Odds API key goes into `.env` in that folder and never into the chat.

## Risks and open questions

- **API access.** Terms are unknown and a key scheme is declared. The disk cache keeps every fetched game usable if access closes.
- **Small sample.** A season is 380 games and the early-season scoring window is smaller still. Expect wide uncertainty, and expect that the backtest may not separate the club part from the roster part. If it cannot, I will say so and keep the simpler model.
- **Players new to the EuroLeague** have no history in our data. They receive the average first-season value of past newcomers, labelled as such. This understates a star signing.
- **Box-score player value measures defence poorly.** The lineup-based challenger after the MVP is the test of whether that matters.
- **Availability.** With no injury feed, upcoming games assume the recent rotation unless you supply absences.
- **Open:** exact 2026-27 tie-break, play-in seeding and home-court rules, to be read from the regulations in step 3; how the eight seasons differ in format, to be read from the schedule endpoint in step 1.

## What I need from you

A project folder on your computer connected to this chat. Python 3.11 or newer is already installed there.

## Changes after approval

The plan above is as approved on 10 October 2026. What was decided or found afterwards, in order. Numbers and reasons are in `docs/TECHNICAL_NOTES.md` (until 12 October 2026 they were in the README).

1. **Storage and tooling.** Feature tables are built by SQL run from Python, not by dbt. PostgreSQL, Prefect and Redis were not added; the API and the dashboard read the DuckDB file directly. Decided by the developer and reported; the owner did not object.
2. **Rosters from the league's own registration lists.** The league API lists every club's registered players with start and end dates, positions and coaches. Rosters as of any tip-off come from there, which keeps the "only data from before tip-off" rule intact.
3. **Head-coach component removed** (owner's decision, option 1). It added nothing and its fitted size was unstable. The roster component was kept although its gain is not distinguishable from zero.
4. **Stage two is not published.** Logistic regression and LightGBM were both built and measured; neither beat the rating model out of sample. By change 7 of the plan the rating model with the roster start is the published model.
5. **The two teams' scoring in one game is treated as correlated.** Found while fixing forecasts that were too cautious about favourites.
6. **Simulator.** The absence sensitivity run of change 6 was not built. Instead there are two scenarios, with and without the absences entered by hand. Tie-break steps 4 and 5 are not implemented. Format rules were taken from second-hand sources and checked against the real pairings of seven seasons.
7. **Players to Watch is two lists** (owner's decision): the players expected to produce most, and the rotation players expected to beat their own norm. The brief's product formula was measured and replaced by learned weights. Only the second list beats a reader without a model, and only from about round 7 of a season.
8. **Known absences.** There is no injury feed. Absences are entered by hand in `config/absences.csv` from the league's injury report. Their effect on a team is learned from who did not play in past games, and a long absence is weighted down as the rating model learns it from results.
9. **Market comparison.** `track-record` compares our pre-game probabilities with the market's after each round.
10. **Shot module turned on** (owner's decision, 11 October 2026). Assumption 4 passed: the shot endpoint returns court coordinates for every season loaded. Shots are stored, checked against the box score, summarised by zone and shown on the dashboard. A zone-based matchup was measured and added nothing next to the position-based one, so the player lists stay position-based.
11. **Roster value extended** (owner's request, 12 October 2026). The roster index now combines the box-score value with a lineup-based value (ridge regression over lineup stints), and a team's strength moves during the season when its registered roster changes. Walk-forward log loss 0.6208 → 0.6195; see the README section "Roster value".
12. **Availability replaces the absence shift** (owner's request, 12 October 2026). The roster index counts only players expected to be available (played in one of the team's last three games, or newly registered); hand-entered absences remove players the same way. Walk-forward log loss 0.6195 → 0.6176.
13. **Left-out factors are shown, not used** (owner's request, 12 October 2026). Coach record, extra uncertainty after a coach change, rest, travel, style and zone matchups were each tested and did not improve forecasts. Their measured sizes are stored per run and shown per game as "Why this forecast".
14. **Head coach in the lineup regression; context terms in the rating model** (owner's decision, 12 October 2026). Coaches are credited with what their teams did beyond the sum of their players. Rest, travel, home and away form and a shot-zone matchup blended from players' habits are weighed by the rating model. Walk-forward log loss 0.6176 → 0.6174 (coach) → 0.6181 (context terms, kept by the owner's decision although 0.0007 worse; see the README).
15. **Model tests and forward test** (owner's request, 12 October 2026). Round-resampled comparisons, a tuned Elo yardstick, placebo and sensitivity tests and a segment report are in the README ("Model tests"). Context weights are halved before forecasting. `docs/FORWARD_TEST.md` fixes the forward test against the betting market and the rule for changing the model during the season.
16. **Upgrade rule at 85%; learned box-score value adopted** (owner's decision, 12 October 2026). The box-score part of the roster index is now a statistical plus-minus learned from lineup values on earlier seasons, with advanced statistics among its inputs. Walk-forward log loss about 0.6175 → 0.6165.
17. **Score forecasts and release tidy-up** (owner's request, 12 October 2026). Each game now gets an expected score with 80% ranges for margin and total. The code is linted and formatted with ruff, tested on GitHub Actions and released under the MIT License. The README was rewritten as an overview; the detailed record moved to `docs/TECHNICAL_NOTES.md`.
18. **Upgrade rule at 80%; long-run home split and home games abroad adopted** (owner's decision, 19 October 2026). Two context terms: each team's home and away split over earlier seasons, and a flag for home games played far from the club's home city (`config/home_cities.csv`). Walk-forward log loss 0.6165 → 0.6159.
