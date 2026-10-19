# Forward test and upgrade rule

Written on 12 October 2026, before round 5 of the 2026-27 regular season. Everything below was fixed before any of the games it judges were played.

## What is frozen

The model published on 12 October 2026 (the "champion"): the rating model with the combined roster value (box score and lineup regression, head coaches included), in-season roster changes, availability, and the four context terms at half their fitted weight. The code version is the git commit that adds this file; tag it `champion-2026-10-12`. Its settings are fitted on completed seasons only, so they do not change during the season; only the data does.

Every forecast is stored before tip-off with its run id and code version (`model_runs`). `track-record` scores only forecasts and odds stored before each game's tip-off.

## Market data

Before each round, `round --odds` takes the first odds snapshot (opening). On each match day, within the hour before that day's first tip-off, `snapshot-odds` takes another (closing for that day's games). A round over two days costs three credits, roughly 100 for the regular season out of about 495 left.

## What is measured

Over all games from round 5 on that have a stored forecast and a closing snapshot from before tip-off:

1. **Log loss against the closing market**: our forecast minus the market's, with a 90% interval from resampling whole rounds.
2. **Closing-line value**: in games whose price moved between the two snapshots, the share that moved towards our forecast and the average move in our direction.
3. **Calibration**: the slope of the actual result on our forecast's log-odds (1 is perfect; below 1 means overconfident).

## Pass marks, set in advance

At the end of the regular season (round 38):

- **Holds its own** if log loss is no more than 0.010 worse than the closing market and the calibration slope is between 0.8 and 1.2.
- **Has an edge** if, in addition, closing-line value shows more than 55% of moves towards our forecast with an average move above zero, over at least 150 moving games.
- Anything else is a **fail**, reported as such.

An interim reading after round 15 is allowed, but no decision is taken from it.

## Upgrade rule

The model may change during the season, between rounds, only if the change passes all of these on the walk-forward backtest (2020-21 to the latest round, every season predicted with settings fitted only on earlier seasons), compared with the current model on the same games:

1. Mean log loss is lower, and in at least 80% of round-block resamples (`elsim.models.compare`). (Set at 90% on 12 October 2026, lowered to 85% the same day and to 80% on 19 October 2026, each by the owner's decision; at 80%, a change with no real effect passes about one time in five.)
2. The first ten rounds of the seasons together are not worse by more than 0.001.
3. The gain is larger than the cost of adding a random feature of the same kind (placebo, about +0.001 for one extra fitted setting).
4. Any constant chosen by hand is reported with its neighbours, so the gain is not an artefact of one lucky value.

A change that passes gets a new tag. The champion's forecasts keep being scored by the forward test separately from those of later versions, by code version.
