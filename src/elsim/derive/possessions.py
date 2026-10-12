"""Splits a game's play-by-play into possessions."""

# Events that only the team with the ball can produce.
WITH_BALL = {"2FGM", "2FGA", "3FGM", "3FGA", "FTM", "FTA", "TO", "O"}
POINTS = {"2FGM": 2, "3FGM": 3, "FTM": 1}


def split(events: list[dict]) -> list[dict]:
    """Return the possessions of one game, from flattened events.

    A new possession starts when a different team produces a with-ball event,
    or when a new period starts. Known weakness: free throws for a technical
    foul taken by the team without the ball are counted as a short possession
    of their own, which adds a little to both teams' counts.
    """
    possessions = []
    current = None
    for event in events:
        if event["play_type"] not in WITH_BALL:
            continue
        team, period, second = event["team_code"], event["period"], event["elapsed_seconds"]
        if current is None or team != current["team_code"] or period != current["period"]:
            start = second
            if current is not None and period == current["period"]:
                start = current["end_second"]
            current = {
                "possession_number": len(possessions) + 1,
                "team_code": team,
                "period": period,
                "start_second": start,
                "end_second": second,
                "points": 0,
            }
            possessions.append(current)
        current["end_second"] = second
        current["points"] += POINTS.get(event["play_type"], 0)
    return possessions
