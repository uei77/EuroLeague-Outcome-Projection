"""Checks the rating model on the real 2025-26 season."""

import csv
from pathlib import Path

from elsim.models.state_space import Game, Params, run

PARAMS = Params(game_var=0.15, season_var=4.0, carry_over=0.6, noise_var=166.0, new_team_var=17.0, noise_corr=0.2)


def season_games() -> list[Game]:
    path = Path(__file__).parent / "fixtures" / "team_game_stats_E2025.csv"
    with open(path, newline="", encoding="utf-8") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: (r["tipoff_utc"], r["game_code"]))
    per_100 = lambda r: 100.0 * int(r["points"]) / int(r["possessions"])
    return [
        Game(
            "E2025",
            r["team_code"],
            r["opponent_code"],
            False,
            per_100(r),
            100.0 * int(r["opp_points"]) / int(r["opp_possessions"]),
        )
        for r in rows
        if r["is_home"] == "true"
    ]


def test_a_prediction_does_not_depend_on_its_own_result_or_later_ones():
    games = season_games()
    k = 200
    changed = games[:k] + [g._replace(home_per_100=200.0, away_per_100=50.0) for g in games[k:]]
    forecast = lambda prediction: prediction[:5]  # everything except the score of the result
    assert forecast(run(games, PARAMS)[k]) == forecast(run(changed, PARAMS)[k])
    assert forecast(run(games, PARAMS)[k + 1]) != forecast(run(changed, PARAMS)[k + 1])


def test_unplayed_game_is_predicted_and_changes_nothing():
    games = season_games()
    upcoming = Game("E2025", games[300].home, games[300].away, False, None, None)
    with_upcoming = run(games[:300] + [upcoming] + games[300:], PARAMS)
    assert with_upcoming[300].log_likelihood is None
    assert 0 < with_upcoming[300].p_home < 1
    assert with_upcoming[301] == run(games, PARAMS)[300]


def test_home_team_is_favoured_between_unknown_teams_and_not_on_neutral_court():
    first = run([Game("E2025", "AAA", "BBB", False, None, None)], PARAMS)[0]
    neutral = run([Game("E2025", "AAA", "BBB", True, None, None)], PARAMS)[0]
    assert first.p_home > 0.5
    assert neutral.p_home == 0.5


def test_roster_change_during_season_moves_the_team_by_the_roster_effect():
    params = PARAMS._replace(roster_off=2.0, roster_def=-1.0, roster_move=1.0)
    games = season_games()[:60]
    team = games[40].home
    start = {("E2025", t): 0.0 for t in {g.home for g in games} | {g.away for g in games}}
    later = [g._replace(home_roster=0.5) if g.home == team else g for g in games[40:]]
    before, after = run(games, params, start)[40], run(games[:40] + later, params, start)[40]
    # offence +2.0 x 0.5 and defence -1.0 x 0.5: the home side's margin grows by 1.5
    assert abs((after.margin_per_100 - before.margin_per_100) - 1.5) < 1e-9
    unchanged = [g._replace(home_roster=0.0) for g in games]
    assert run(unchanged, params, start) == run(games, params, start)
    assert run(games[:40] + later, params._replace(roster_move=0.0), start) == run(games, params, start)


def test_context_weights_are_halved_and_nothing_else_changes():
    from elsim.models.backtest import CONTEXT, shrink_context

    params = PARAMS._replace(rest_effect=1.0, travel_effect=0.4, form_effect=-0.2, style_effect=0.1, roster_off=2.0)
    shrunk = shrink_context(params)
    assert all(abs(getattr(shrunk, n) - 0.5 * getattr(params, n)) < 1e-12 for n in CONTEXT)
    assert shrunk.roster_off == 2.0 and shrunk.game_var == params.game_var


def test_total_spread_is_reported_and_wider_than_one_teams_noise():
    first = run([Game("E2025", "AAA", "BBB", False, None, None)], PARAMS)[0]
    assert first.total_sd > PARAMS.noise_var**0.5
