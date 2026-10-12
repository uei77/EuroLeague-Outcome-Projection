"""Checks "Players to Watch" on past rounds.

For the "top" list: did the ten listed players really produce more than the
ten a reader would pick without a model? For the "rising" list: did the ten
listed players beat their own season average by more than rotation players
in general did?
"""

from elsim.players.breakout import LIST_SIZE, ROTATION_LEVEL, add_scores, fit_weights, pick

# How each list picks its ten players for a round.
LISTS = {
    "learned score": "score",
    "brief's product": "score_product",
    "season average": "season_average",  # what a reader would pick without a model
}
MIN_TRAIN_SEASONS = 2


def walk_forward(rows: list[dict]) -> tuple[list[dict], dict]:
    """Score every regular-season round with weights fitted only on earlier
    seasons. Returns one record per round and list, and the weights used per
    season. A listed player who did not play counts as zero."""
    seasons = sorted({r["season_code"] for r in rows})
    records, weights_by_season = [], {}
    for season in seasons[MIN_TRAIN_SEASONS:]:
        weights = fit_weights([r for r in rows if r["season_code"] < season])
        weights_by_season[season] = weights
        test = [r for r in rows if r["season_code"] == season and r["phase"] == "RS" and r["game_played"]]
        add_scores(test, weights)
        for round_number in sorted({r["round"] for r in test}):
            in_round = [r for r in test if r["round"] == round_number]
            starters = [r for r in in_round if r["played"] and r["is_starter"]]
            for name, key in LISTS.items():
                picked = sorted(in_round, key=lambda r: -r[key])[:LIST_SIZE]
                records.append(
                    {
                        "season": season,
                        "round": round_number,
                        "list": name,
                        "valuation": sum(r["actual"] for r in picked) / LIST_SIZE,
                        "points": sum(r["points"] or 0 for r in picked if r["played"]) / LIST_SIZE,
                        "assists": sum(r["ast"] or 0 for r in picked if r["played"]) / LIST_SIZE,
                        "played": sum(r["played"] for r in picked) / LIST_SIZE,
                        "starters_valuation": sum(r["actual"] for r in starters) / len(starters),
                    }
                )
            # The "rising" list against all rotation players of the round,
            # first counting a player who did not play as zero, then only
            # among those who played.
            rotation = [r for r in in_round if r["level"] >= ROTATION_LEVEL]
            rising = pick(in_round, "rising")
            over = lambda group: sum(r["actual"] - r["season_average"] for r in group) / len(group)
            on_court = lambda group: [r for r in group if r["played"]]
            records.append(
                {
                    "season": season,
                    "round": round_number,
                    "list": "rising",
                    "picked_over_own_average": over(rising),
                    "rotation_over_own_average": over(rotation),
                    "picked_played": len(on_court(rising)) / len(rising),
                    "rotation_played": len(on_court(rotation)) / len(rotation),
                    "picked_over_when_played": over(on_court(rising)),
                    "rotation_over_when_played": over(on_court(rotation)),
                }
            )
    return records, weights_by_season
