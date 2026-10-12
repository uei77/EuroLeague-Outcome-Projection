# Technical notes

The full record of what was built, measured, adopted and rejected, with every number behind it. The README gives the overview; the plan and its changes are in `docs/PLAN.md`, the forward test in `docs/FORWARD_TEST.md`.

## Setup (Windows PowerShell, from this folder)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Commands

Run everything from this folder with the virtual environment active.

```powershell
python -m elsim.cli round            # after a round: fetch, load, predict, simulate
python -m elsim.cli round --odds     # the day before a round: the same, plus an odds snapshot (one credit)
python -m elsim.cli snapshot-odds    # each match day, within the hour before the first tip-off (closing odds, one credit)
python -m elsim.cli odds-plan        # prints when those closing snapshots are due for the coming match days
streamlit run dashboard/app.py       # the dashboard, in the browser
python -m uvicorn elsim.api.app:app  # the API, at http://127.0.0.1:8000/docs
```

`round` runs these in order, and each can be run on its own: `fetch-all`, `fetch-people`, `snapshot-odds` (only with `--odds`), `load`, `track-record`, `predict`, `simulate`. `track-record` compares our pre-game probabilities with the market's on finished games, using only forecasts and odds stored before each tip-off. `backtest`, `backtest-players`, `backtest-simulator` and `backtest-absences` reproduce the evaluation tables; the last two need `backtest` to have been run once. `snapshot-odds` needs `ODDS_API_KEY` in a `.env` file (copy `.env.example`). Before a round, update `config/absences.csv` from the league's injury report. If `load` stops because a venue has no coordinates in `config/venues.csv` (a club playing somewhere new), add that venue's city and coordinates and run it again.

The API has seven read-only endpoints, `/run`, `/games`, `/explanations`, `/players`, `/simulation`, `/track-record` and `/zones`. Each answers `{"run_id": ..., "data": ...}` for the latest run.

## Published model

The published game model is the rating model with a roster component: each team is valued at every tip-off by the registered players expected to be available, which sets its starting point for the season and moves it when players are signed, leave, or stop playing. Walk-forward results, every season predicted with settings fitted only on earlier seasons (log loss, lower is better):

| Games | n | Constant home-win rate | Tuned Elo | Rating model | + box-score roster start (until 12 Oct 2026) | + combined roster value, in-season changes | + availability | + head coach in lineup value | + context terms, full weight | + context terms, half weight (now) |
|---|---|---|---|---|---|---|---|---|---|---|
| E2020 to E2026 | 2,058 | 0.6629 | 0.6268 | 0.6222 | 0.6208 | 0.6195 | 0.6176 | 0.6174 | 0.6181 | 0.6175 |
| First ten rounds | 590 | 0.6654 | 0.6401 | 0.6355 | 0.6333 | 0.6316 | 0.6284 | 0.6280 | 0.6273 | 0.6274 |

The roster-value step gained 0.0012 ± 0.0009 and the availability step 0.0019 ± 0.0010, each better in five of the seven seasons. The head-coach step gained 0.0002 ± 0.0003. The context terms (rest, travel, home and away form, shot-profile matchup) were put in by the owner's decision. At their fitted weight they cost 0.0007 ± 0.0010; at half that weight they are level with leaving them out, so they are used at half weight; see "Context terms" and "Model tests" below. See also "Roster value" and "Availability and known absences".

The stage-two comparison and the simulator check below were measured with the earlier roster start and have not been rerun:

| Games | n | With roster start | + logistic regression | + LightGBM |
|---|---|---|---|---|
| E2022 to E2026 | 1,431 | 0.6173 | 0.6189 | 0.6288 |

Neither stage-two candidate beat the rating model, so by the rule agreed in the plan neither is published. `backtest` reproduces these tables and writes `reports/calibration.png`.

## Expected scores

Each game also gets an expected score: each team's expected points per 100 possessions from the rating model, at the two teams' average pace so far this season (72 possessions before a team's first game), with 80% ranges for the margin and the total from the model's own uncertainty. On the 2,058 walk-forward games, against forecasting every earlier season's average score: home points off by 8.0 (8.8), away points 8.2 (8.9), total 13.2 (14.5), margin 9.2 (9.9). The 80% ranges held the real margin in 82% of games and the total in 77%; the total's range is slightly narrow because pace is taken as known. Overtime points are included in the real scores. `backtest` prints these figures (`src/elsim/models/score.py`).

## EuroCup check

The same code, unchanged, on the EuroCup (`config/settings_eurocup.toml`, data kept in `data/eurocup`). Training seasons 2020-21 to 2022-23; walk-forward forecasts of 2023-24, 2024-25, 2025-26 and three rounds of 2026-27, 616 games; optimiser started from the EuroLeague settings, every setting refitted on EuroCup seasons only. Log loss (accuracy): home team always wins 0.6823 (58.0%), tuned Elo 0.6183 (66.9%), ratings alone 0.6141 (65.6%), published model 0.6137 (67.0%). Against Elo -0.0045 [-0.0133, +0.0047], 79% of resamples, three of four seasons (2023-24, when home teams won only 53%, went to Elo); against ratings alone -0.0003, 55%. Calibration by bin: 30% forecast / 30% won, 46/42, 55/52, 65/72, 75/77, 86/81. Expected scores: mean absolute error 9.1 home, 8.8 away, 14.0 total, 10.6 margin (usual score: 9.9, 9.9, 15.1, 11.9); 80% ranges held 77% of margins and 75% of totals. Five played games failed to download (U2020 56 and 120, U2022 11, U2023 61, U2025 62) and are left out. No absences were entered and EuroCup arenas have no coordinates, so travel is zero for their games.

## Players to Watch

`predict` prints and stores two lists per round, by the owner's decision.

- **top**: the ten players expected to produce most (valuation, the league's PIR). On 178 past rounds this list averaged 15.42 against 15.53 for simply taking the ten highest season averages; the difference is not distinguishable from zero. It is shown for what it is: the best players, with the parts of their score.
- **rising**: the ten rotation players expected to beat their own norm, ranked by the form and matchup parts of the score. On past rounds the listed players beat their own season average by 0.79 when they played, against 0.09 for rotation players in general, and they played more often (92% against 86%). In a season's first six rounds the list has shown no edge.

The brief's formula, form x matchup x team at face value, was measured and is significantly worse than the season-average list (15.07). The weights of the parts are learned instead: level 0.98, minutes form 0.47, rate form 0.13, matchup 0.44, team 0.57. `backtest-players` reproduces these tables.

## Simulator check

`backtest-simulator` simulates the rest of the regular season from rounds 5, 15 and 25 of five past seasons (2020-21 and 2022-23 to 2025-26), with settings fitted only on earlier seasons, and compares with how each season ended. 2019-20 and 2021-22 are left out: one was stopped early, the other had results annulled.

| After round | Team-seasons | Brier, top-eight finish | No skill | Mean error in wins | Real wins inside the 50% / 80% / 95% interval |
|---|---|---|---|---|---|
| 5 | 92 | 0.164 | 0.246 | 2.9 | 57% / 85% / 95% |
| 15 | 92 | 0.153 | 0.246 | 2.2 | 50% / 89% / 97% |
| 25 | 92 | 0.091 | 0.246 | 1.3 | 63% / 88% / 97% |

A stated chance of a top-eight finish matched what happened: of the team-seasons given 30% to 50%, 43% made it; of those given 50% to 70%, 58%; of those given 70% to 90%, 75%. The win-total intervals are not too narrow; if anything they are slightly wide. Only the regular season is checked. Title and Final Four chances cannot be checked this way: five seasons give five champions.

## What injury information is worth

(Measured with the earlier absence shift, before availability entered the roster index.)

`backtest-absences` hands the model, as if known before tip-off, which rotation players did not play in each past game: the best case for any injury feed. On 1,730 games log loss went from 0.6154 to 0.6149. Knowing every absence is worth almost nothing on average, because most absences are of ordinary rotation players and the rating model picks lasting ones up from results.

A star going out is different in direction, though not proven: in the 225 games where one team alone was missing a player of level 15 or more during his first five games out, the model gave that team 52.0% and it won 48.9%; its margin fell short of the forecast by 1.9 points per 100 possessions (standard error 1.1). That is the size the absence shift applies for such a player (0.108 x 15 = 1.6), so the shift is kept for hand-entered absences and shown beside, not instead of, the model's own forecast.

## Shot module

`enable_shot_data` in `config/settings.toml` turns the shot module on (it is on). It uses a league endpoint that is not in the API documentation. With it on, `fetch-all` also saves each game's shots, `load` fills the `shots` table and two season summaries by court zone, and the dashboard gets a Shots tab: what each team allows from each zone against the league, and a shot chart per player. With it off, no shot file is fetched, the tables stay empty, and `predict` gives exactly the same output (checked by running it both ways and comparing).

Checked on the real data: 317,914 field-goal attempts in 2,565 games; made and missed twos and threes per team equal the box score in every one of them. Four games have no shot file.

Six zones, left and right merged: rim, paint, short mid-range, long two, corner three, above-break three. Two-pointers use the league's own zone letters; three-pointers are split into corner and above the break by their distance from the baseline. Positions come on a coarse grid from the source.

**The zone data does not feed the forecasts.** The brief expected the player matchup to go by court zone once shot data was on. That was built (what the opponent allows per shot in each zone above the league, weighted by where the player shoots) and measured on 47,000 player-games. On its own it had a small effect (t 3.6, against 9.4 for the position-based matchup). With both in the model, the zone-based one added nothing (t 0.2). For points scored, neither had an effect. So Players to Watch stays position-based and says so; the zone tables describe.

## Model tests

Run on 12 October 2026 against the walk-forward backtest (2,058 games, 2020-21 to round 4 of 2026-27). Differences are in log loss (negative is better) with a 90% interval from resampling whole rounds, since games of one round are not independent (`src/elsim/models/compare.py`). The forward test against the betting market, and the rule for changing the model from now on, are in `docs/FORWARD_TEST.md`.

**Against a tuned Elo** (`src/elsim/models/elo.py`; K, home edge, season carry-over and margin weighting chosen on earlier seasons): Elo 0.6268, published 0.6181 at the time of the test; difference -0.0087 [-0.0135, -0.0041], better in all seven seasons. Blending Elo into the published forecast (weights fitted on earlier seasons) made it worse (+0.0018): the published model already holds what Elo knows.

**Each adopted step, re-checked with round resampling:** roster value -0.0012 [-0.0027, +0.0003] (better in 92% of resamples), availability -0.0019 [-0.0035, -0.0004] (98%), head coach -0.0002 [-0.0007, +0.0003] (73%). The whole roster component against the plain rating model: -0.0047 [-0.0077, -0.0018], better in all seven seasons.

**Placebo tests.** The roster z-scores shuffled between teams of the same season: +0.0008 and +0.0009 (two shuffles), against -0.0047 for the real ones; the roster signal is real. A random number in place of the shot-profile matchup, fitted the same way: +0.0008, +0.0016, +0.0017 (three draws). Adding one fitted setting that carries no information therefore costs about 0.001 in this backtest; that is the bar a new term has to clear.

**Hand-set constants.** Availability window of 2 or 5 games instead of 3: +0.0007 and +0.0014. Lineup ridge penalty 3e4 or 3e5 instead of 1e5: +0.0011 and +0.0004. The values in use were set before these runs, and their neighbours are worse but not by much: the result does not hang on one lucky value.

**Where the model is strong and weak** (published at the time of the test, against the plain rating model):

| Games | n | Elo | Rating model | Published |
|---|---|---|---|---|
| Rounds 1-5 | 315 | 0.6649 | 0.6515 | 0.6442 |
| Rounds 6-15 | 550 | 0.6396 | 0.6354 | 0.6358 |
| Rounds 16 on | 1,057 | 0.6066 | 0.6040 | 0.5983 |
| Play-in, playoffs, Final Four | 136 | 0.6439 | 0.6423 | 0.6405 |
| A team missing players | 1,045 | 0.6176 | 0.6117 | 0.6057 |
| Favourite at 70% or more | 642 | 0.5101 | 0.5088 | 0.5003 |
| Close calls (40-60%) | 729 | 0.6895 | 0.6878 | 0.6867 |

Rounds 6 to 15 are where the roster component adds nothing. The margin forecast is well calibrated: 50%, 80% and 95% intervals held 50.5%, 81.4% and 94.1% of actual margins, with an average error of +0.15 points per 100 possessions. Team by team, wins minus expected wins vary by 2.6 per season, slightly less than chance alone would give (2.8); no team is consistently misjudged beyond what chance explains.

**Crowd and referees** (12 October 2026, from fields the league's schedule already carries: attendance, venue capacity and the assigned referees). Crowd: the home team's average log attendance in its earlier home games (this season, and last season at half weight), shrunk to the league's average by five games. Referees: the crew's average home bias, the home margin per 100 possessions in each referee's earlier games against the league average, shrunk by 50 games. Added to the rating model like the context terms, against the published model on the same games: crowd and referees together -0.0001 [-0.0009, +0.0007] (57% of resamples), crowd alone -0.0003 [-0.0010, +0.0005] (71%), better in the first ten rounds (-0.0009 to -0.0012) but short of the upgrade rule overall. The crowd weight was stable (about +2.4 points per 100 possessions per unit of log attendance, roughly +1 for a typical difference between two clubs); the referee weight was not. Both are left out of the forecast and shown under "Why this forecast". Referees are assigned close to tip-off, so their part shows as zero until the schedule lists them.

**Advanced statistics and a learned box-score value** (12 October 2026). `load` now builds `player_advanced` (true shooting, effective FG, three-point and free-throw rates, usage, assist, rebound, steal, block and turnover percentages, PIR per 40) and `team_advanced` (ratings, pace, four factors for and against). A box-score value learned from lineup values on earlier seasons (a statistical plus-minus; true shooting, assists, steals and defensive rebounds weigh most) in place of PIR in the roster index: -0.0010 [-0.0026, +0.0005], better in 87% of resamples, four of seven seasons; ridge penalties of 25 and 100 instead of 50 gave -0.0010 (86%) and -0.0011 (88%). Adopted once the owner set the upgrade rule at 85% (`src/elsim/features/box_value.py`); PIR per 40 minutes is still used for expected minutes. Valuing rosters against replacement level instead of as an average: +0.0003, rejected.

**Player values updated during the season** (12 October 2026). Two ways of letting this season's games move the roster index, each against the published model: this season's box scores blended into each player's learned box-score value (as if the pre-season value were worth 400 minutes) -0.0000 (51% of resamples), no gain; expected minutes from this season's games (last season's minutes per game worth three games) +0.0025, worse in all seven seasons; both together +0.0021. The likely reason: what a team does this season already reaches its rating through its results, and a roster index that follows the same games moves the team a second time. Rejected; the roster index stays built from earlier seasons, registrations and availability.

**Accuracy ceiling.** Ratings fitted on every other game of the same season, future ones included, pick 65.0% of winners; the published model picks 65.7%. Even exact knowledge of true strength would give about 67-70%, because one game's margin varies by 17.9 points per 100 possessions while true differences vary by 8-10. On games where the published model gives the favourite 65% or more (46% of games) the favourite won 74.7%; at 70% or more (30%), 79.5%.

**Domestic-league schedules** (12 October 2026). Rest counts EuroLeague games only, so fatigue from domestic games is invisible. API-Sports (API-Basketball) lists the nine domestic leagues of this season's clubs, but its free plan gave access to none of their seasons, current or past, so nothing was fetched. Since rest measured on EuroLeague games alone came out at zero, a paid plan or nine league websites were not pursued.

**Tried and rejected in this round of tests:** extra rating drift in each team's first ten games of a season (fitted to zero once four or more seasons were available); fitting the settings on win probabilities instead of points per 100 possessions (unstable, with degenerate settings in some seasons); an Elo blend (above).

## Context terms

By the owner's decision (12 October 2026) the rating model weighs four pieces of game context, each with a weight fitted on earlier seasons together with the model's other settings. They are added to the home margin before the game:

- **Rest:** days since each team's previous EuroLeague game (capped at 4), home minus away. Domestic games are not in our data.
- **Travel:** distance from each team's usual home venue that season to the game's venue, away minus home, in 1,000 km. Venue coordinates are in `config/venues.csv` (city level, entered by hand). Teams playing "home" games abroad count as travelling.
- **Home and away form:** for each team, (net rating at home - net rating away) / 2 so far this season, above the league's usual value in earlier seasons and shrunk by g / (g + 10) after g games; the home team's home form plus the away team's away form.
- **Shot-profile matchup:** where each team is expected to shoot, by court zone, against how well the opponent has defended each zone so far this season (pulled to the league by 50 shots per zone). A team's profile blends its own shots so far this season with the habits of the players it is expected to field (the players of its last three games; before its first game, its registered players with last season's minutes), the players counting as much as 400 of the team's own shots. A player's habit is his attempts per second by zone over this season so far and earlier seasons, each further back counting half.

Fitted on all completed seasons the weights are: rest -0.06 per day, travel +0.47 per 1,000 km, form -0.10, shot-profile matchup -0.09 per point per 100 shots (points per 100 possessions). Form and the matchup come out slightly negative: a team that has played unusually well at home, or whose profile looks favourable, tends to do a little worse than that suggests next time, so the model leans against them. In the walk-forward test the four together made log loss worse by 0.0007 ± 0.0010 overall: clearly worse in the two seasons whose weights were fitted on only one or two earlier seasons (rest then came out at +3.4 and +0.9 per day), better in 2022-23, 2025-26 and the first rounds of 2026-27. With eight seasons to fit on the weights are stable. The fitted weights are halved before forecasting (`CONTEXT_SHRINK` in `src/elsim/models/backtest.py`): the placebo test below shows that fitting even one random feature this way costs about 0.001, so part of each fitted weight is noise. Half weight was chosen among full, half and none on the same test seasons, so its small edge over full weight is optimistic. Taking the terms out means removing `CONTEXT` from the published variant.

The season simulation adds the same context to each remaining game.

## Availability and known absences

There is no injury feed. Absences enter the forecast in one way: through the roster index, which counts only the registered players expected to be available.

- **From the data, for every game:** a registered player counts as available if he played in one of his team's last three games, joined the team after those games began, or was registered within the last 14 days. This uses only games finished before the tip-off, so it can be tested on past seasons; it is what improved log loss from 0.6195 to 0.6176. For games not yet played, the rule applies to each team's next game; later games count every registered player, because nobody knows yet who will be missing then. The constants 3 and 14 were chosen once and not tuned.
- **By hand, for games to come:** `config/absences.csv` holds absences entered from the league's injury report for each round ("Injury report: Round N"), checked against two news sites that keep running lists: Basketnews' daily-updated EuroLeague injury report and Eurohoops' round previews (RotoWire's EuroLeague injury feed is a third check). They are read by hand, never fetched by code. One line per player with the date he is out until and the source. Players who have missed the team's last three games are already left out by the data rule, so the file matters most for two cases: a player who played recently and is now out (he would otherwise still count), and a long absence, because games beyond each team's next one count every registered player. An absence given as "indefinite" is entered until the end of the next few rounds and re-checked each round. Names must be written exactly as the league writes them ("JAMES, MIKE"); an unknown name stops the run. These players are also left out of the available roster for the current season's unplayed games up to that date. `predict` shows the forecast with and without them, and `simulate` stores two scenarios, `baseline` and `with_absences`. The players are also left off both Players to Watch lists.

A hand-entered absence is never allowed to make a team stronger. Because the roster index is a minutes-weighted average, leaving out a player who rates below the one who moves up into the ten can raise it; the forecast with absences then keeps the team where it was. (The same quirk exists in the data rule and is a candidate for the next upgrade test: valuing a roster against replacement level instead of as an average.) A change in the available roster moves the team by the same roster effect as a signing. Because the move is made in the rating model's state, the model then judges the team's results against the weakened team, so a long absence is not counted twice. This replaces the earlier hand-made absence shift and its learned-absorption weighting (still available as `backtest-absences` for the record).

## Roster value

A team's roster index is the minutes-weighted average value of the ten registered players expected to play most, using only seasons before the current one. Two player values are combined, each turned into a z-score among that season's teams at their first game, and the published roster z-score is the z-score of their sum:

- **Box-score value:** the league's valuation (PIR) per 40 minutes, as described under Decisions.
- **Lineup value:** how the scoring margin moved while the player was on the floor, with the other nine players held fixed (ridge regression over 84,354 lineup stints from games that passed the five-players check; up to three earlier seasons, each further back counting half; players new to the league get the average value of last season's newcomers).

Each side's head coach is a term in the same regression, so what a team did beyond the sum of its players is credited to its coach (coaches who move between clubs make the two separable). The coach's value, divided by five because it acts on the whole lineup, is added to the lineup index of the team he is registered with at each tip-off, so a coaching change moves the team like a roster change. With coaches, the regression predicted next season's stints marginally better (R² 0.00206 against 0.00203) and game forecasts gained 0.0002 ± 0.0003; the change is small because coach values are strongly shrunk.

How well each predicts a team's net rating for the season, together with last season's net rating (114 team-seasons): last season alone R² 0.356; with box-score value 0.395; with lineup value 0.437; with both 0.441. The lineup value correlated better with the season's outcome in six of seven seasons. In the walk-forward game forecasts, lineup value alone and the combination gave the same overall log loss (0.6199), and the combination was steadier from season to season, so the combination is used.

During a season, a team's roster is re-valued at every tip-off from the registration dates. When it changes, the team's offence and defence move by the same roster effect that applies at the season start, times the change in z-score. About two thirds of team-games have a roster at least slightly different from the season's first game; one in five differs by more than 0.1 standard deviations. For upcoming games the roster is whoever is registered for that date, so a signing shows up once the league registers it.

## Why this forecast

`predict` also stores, for every unplayed game, its forecast split into parts that add up to the expected margin (team ratings, home edge, registered players currently not playing, and the four context terms), and next to it what each left-out factor would add: the three style matchups, the team-only zone matchup, the coaches' earlier win rates, the home crowd and the referees. Their sizes are measured on how far all past games ended from the published model's forecast; `predict` prints them and the dashboard shows them under "Why this forecast" on the Games tab (API: `/explanations`). They are never added to the forecast, because each was tried as part of it and did not improve forecasts of seasons it had not seen. A size within about two standard errors of zero can be chance; on 12 October 2026 the largest were offensive rebounding (+0.77 ± 0.33 points per 100 possessions for a typical difference between two teams), the coach's win rate (+0.53 ± 0.35) and the team-only zone matchup (-0.41 ± 0.35, the wrong sign).

## Tried and not adopted

Each of these was built, measured on past seasons and removed because it did not improve the forecasts. They are listed so that nobody builds them a second time without a new reason.

- **A home edge of its own for each team.** Fitted on earlier seasons, the model set the allowed difference between teams to zero in all six walk-forward fits, and the forecasts did not change (log loss 0.62042 both ways). The data shows why: a team's home edge in one season says almost nothing about its home edge in the next (correlation 0.085 over 113 team-season pairs), and the spread of home edges between teams (5.5 points per 100 possessions) is what chance alone would produce (5.6). The league-wide home edge stays.
- **Head-coach continuity** in the season start: no gain, unstable size.
- **A coach's earlier record** (owner's idea, 12 October 2026). For every game, each head coach's earlier EuroLeague games were summarised four ways, shrunk towards zero as if by 20 extra games: win rate overall, win rate with his current team, and how far his teams beat the rating model's forecast, overall and with his current team. None of them predicted what the rating model missed in the 2,058 games from 2020-21 on (largest t-value 1.06, for win rate overall), nor when only coaches new at their team were counted. The record with the current team is already what the team's rating is made of, and a win rate overall mostly reflects the rosters a coach had. Coach history in the data starts in 2018-19 and covers the EuroLeague only.
- **Extra uncertainty when the head coach changes.** 94 changes (52 during a season). Teams were 5.6 ± 0.9 points per 100 below forecast in the ten games before a mid-season change and 0.6 ± 0.9 above it in the ten after, so the rating model already follows them. Given a separate allowance for a coach change, the model set it to zero in all five walk-forward fits it was given (2020-21 to 2024-25).
- **Logistic regression and LightGBM** on top of the rating model, with rest days, recent form and style mismatches: no gain, LightGBM clearly worse.
- **Style matchups** (shooting, offensive rebounding and turnovers, each a team's season-to-date rate against the opponent's allowed rate) **and a team-only shot-zone matchup**, as a shrunk correction to the forecast margin learned from earlier seasons' forecast errors: log loss 0.6122 to 0.6130 on 1,730 games (E2021 to E2026), worse. (Rest, travel, home and away form and a player-blended shot-zone matchup were later put inside the rating model by the owner's decision; see "Context terms".)
- **A coach's over-performance by team-season** (team net rating beyond what last season and the roster predicted, averaged over a coach's earlier seasons): correlation with the next season's over-performance 0.002 over 110 team-seasons. The lineup-regression version of the same idea was adopted instead (see "Roster value").
- **Fitting the size of in-season roster changes separately.** Fitted on points per 100 possessions, it came out at 2.6 to 5.2 times the season-start effect, and made win forecasts worse (log loss +0.0009 against a fixed factor of 1). The factor is fixed at 1.
- **A zone-based player matchup** from the shot data: nothing beside the position-based one.
- **The brief's Breakout Score product** at face value: worse than ranking by season average.
- **Team expected points in the "rising" ranking**: no better than chance on its own.

## Decisions

- The API reads the DuckDB file directly; there is no Redis. The data changes once per round and has one reader, so a cache would add an install (Redis needs WSL or Docker on Windows) without making anything faster or safer. This departs from the brief's step 5 wording.
- The dashboard reads the database through the same query functions as the API (`src/elsim/api/queries.py`) instead of calling the API over HTTP, so one command starts it and the two cannot disagree.
- The dashboard is in English, like the code and the command output.

- A registered player who has not appeared in any box score this season is expected to play only at his team's first game or within 14 days of his registration. Otherwise he is taken to be a long-term absentee. This removed injured players from the lists and raised the share of listed players who actually played.

- The matchup part is what the opponent has allowed a position above what those players normally produce, not the raw production it has allowed. Tested side by side, this adjusted measure keeps its effect and the raw one loses it.
- The team part stays in the score but is left out of the "rising" ranking. On its own it picked no better than chance, and it compares expected points with a team's own average, which is noisy early in a season.
- A player is expected to play if he played in one of the last three games he was listed for, or has not been listed yet this season. A listed player who then does not play counts as zero in the evaluation.
- In `backtest-players` the team part uses the rating model with the settings of the latest run, which were fitted on all completed seasons. The score weights themselves are fitted only on seasons before the one being scored.
- `tests/fixtures/` holds real league data for 2025-26 (about 1 MB). Keep the repository private.

- `simulate` uses the settings of the latest `predict` run and stores its result under the same run id, so game forecasts and season probabilities of one run belong together.
- Each simulated path draws every team's strength once from the rating model's current belief, uncertainty included, and keeps it for the whole path. Form drifting during the season is not simulated. An earlier version of this note said that this makes the probabilities too confident; the simulator check below shows that it does not.
- A simulated game is a score difference in points. Its sign gives the winner; rounded, it is the score difference used in the table; rounded to zero it stands for an overtime game, which counts as level in the standings score, as in the real rules.
- Table tie-break steps 4 and 5 (points scored, sum of quotients) are not implemented, because scores are not simulated. A tie surviving step 3 is broken at random and counted: 54 of 100,000 paths in the first run.
- The table, play-in and playoff rules were checked against real seasons: for 2018-19 and 2020-21 to 2025-26 the table produced by `simulate/table.py` gives exactly the playoff pairings (1 v 8, 2 v 7, 3 v 6, 4 v 5) and play-in games that were played. The one exception is 2021-22, where the league annulled the results of the three excluded clubs and this code does not.
- The absence sensitivity run from the plan is not built yet.

- The head-coach component was removed after measurement: it added nothing overall, made the first ten rounds worse, and its fitted size swung between 0.02 and 0.85 from season to season.
- The roster component was kept by the owner's decision. Its gain (0.0014 log loss) is not distinguishable from zero, but its fitted effect is stable across all seven fits: about +1.1 points per 100 possessions on offence and -0.4 on defence per standard deviation of roster index. With the combined roster value the fitted effect is larger, about +1.6 to +2.4 on offence and -0.7 to -1.5 on defence, shrinking as more seasons enter the fit.
- Stage two is trained only on rating forecasts that were themselves out of sample. Trained on in-sample forecasts it became overconfident and looked worse than it is.
- Stage two does not use player absences. For past games they are only known from the box score, that is, after the game.
- `predict` fits the rating model's settings on the completed seasons only, then runs it through every played game. Expected margin is in points at the two teams' average pace so far this season.
- A run id is the UTC time of the run. `model_runs` stores the git commit when the project is a git repository, and NULL otherwise.
- The market probability shown next to ours is the median over bookmakers of the home probability after removing each bookmaker's own margin, from the latest snapshot.

- Rosters and coaches come from the league's per-club list of registered people, which carries registration start and end dates. A team's roster for a game is whoever was registered at tip-off. Checked against box scores: of 55,572 player appearances, 8 were by a player not registered with that club at that time.
- A player's value is the league's own valuation (PIR) per 40 minutes over earlier seasons, each season further back counting half, pulled towards the first-season average of past newcomers as if by 400 extra minutes. The constants 0.5, 400 and 10 were chosen once and not tuned.
- The lineup value's ridge penalty (1e5) was chosen by how well each penalty predicted the next season's stints; that choice looked at all seasons, the forecasts themselves did not.
- The optimiser's search starts with an explicit step in every setting. With its default step, a setting starting at zero was never moved, which at first made the roster effect look like exactly zero.

- The two teams' points per 100 possessions in one game are allowed to move together (fitted correlation about 0.21). Treating them as independent made the model too cautious about favourites; with the correlation, log loss over 2,058 out-of-sample games went from 0.6249 to 0.6220.

- Final Four games are treated as neutral-court games (no home edge). The schedule's own neutral-venue flag is set for only 2 of 25 Final Four games, so it is not used.
- The rating model's five settings are fitted by how well it predicted points per 100 possessions (both teams), not wins, because that uses more of each game's information. League level and home edge drift slowly with fixed, unfitted variances.
- A team seen for the first time starts at league average. This is known to be generous to newcomers and is revisited with the roster-based season start.

- Feature tables are built by SQL run from Python (`src/elsim/features/`), not by dbt. With a handful of tables rebuilt in one command, dbt would add an install and a second way of running things without adding checks we do not already have. This departs from the plan and can be revisited.
- A possession starts when a different team produces a with-ball event (shot, free throw, turnover, offensive rebound) or a new period starts. Counted this way, a team averages 71.3 possessions a game against 71.95 from the usual box-score estimate, with correlation 0.972, and the two teams of a game differ by at most 2 in 2,565 of 2,569 games.
- Every feature takes its history from the `team_history` view in `features/asof.py`, which admits only same-season games that tipped off strictly before the game in question. `tests/test_no_leakage.py` deletes a game and everything after it and requires the game's features to stay the same.
- Team features are season-to-date ratios of sums and are not adjusted for opponent strength; that adjustment belongs to the rating model in step 2.

- Odds snapshots are saved as one file per run under `data/raw/odds/` and never overwritten, because past odds cannot be fetched again on the free plan.
- The Odds API team names are mapped to league team codes only through `config/team_aliases.csv`, which is checked by hand. An unknown name stops the load; nothing is matched by similarity.

- `load` rebuilds `data/euroleague.duckdb` from the raw files every time, so the database can always be reproduced from `data/raw` alone.
- `game_checks` has one row per played game. A game with `has_data = false` returned an empty response from the source and stays missing. A game with `five_check_passed = false` keeps its scores and box score but must be left out of lineup features.
- Overtime periods are counted from end-of-period markers, not from "BP" events, because substitutions often come before "BP".
- A clock marker that is empty or negative keeps the clock of the event before it.
- Fouls committed are rebuilt from the play types CM, OF, CMU, CMT, CMD, CMT1, CMU_DI, CMU_FL and CMTI. Five team-games differ from the box score by one or two fouls, all next to coach or bench fouls; they are listed in `game_checks.totals_mismatch` and not corrected.

- Ingestion uses only the Python standard library, so fetching data needs no installed packages.
- A response is cached only when it is non-empty, valid JSON. In `fetch-season` and `fetch-all` a failed game is reported and skipped; running the same command again retries only the failures.
- The current season's schedule is fetched afresh on every run, because games change from unplayed to played. Everything else is fetched once.
- Requests are at least one second apart (`config/settings.toml`).
- The league hosts are reachable only from this computer, so every fetch command is run here by hand.
