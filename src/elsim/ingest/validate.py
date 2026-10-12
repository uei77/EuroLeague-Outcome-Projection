"""Rebuilds team totals from play-by-play and compares them with the box score."""

from collections import Counter

# Box score field -> play types whose count must equal it.
COUNTED = {
    "FieldGoalsMade2": ["2FGM"],
    "FieldGoalsAttempted2": ["2FGM", "2FGA"],
    "FieldGoalsMade3": ["3FGM"],
    "FieldGoalsAttempted3": ["3FGM", "3FGA"],
    "FreeThrowsMade": ["FTM"],
    "FreeThrowsAttempted": ["FTM", "FTA"],
    "OffensiveRebounds": ["O"],
    "DefensiveRebounds": ["D"],
    "Assistances": ["AS"],
    "Steals": ["ST"],
    "Turnovers": ["TO"],
    "BlocksFavour": ["FV"],
    "BlocksAgainst": ["AG"],
    "FoulsReceived": ["RV"],
    "FoulsCommited": ["CM", "OF", "CMU", "CMT", "CMD", "CMT1", "CMU_DI", "CMU_FL", "CMTI"],
}


def mismatches(team_code: str, team_totals: dict, events: list[dict]) -> list[str]:
    """Return the box score fields that play-by-play does not reproduce."""
    counts = Counter(e["play_type"] for e in events if e["team_code"] == team_code)
    wrong = [field for field, play_types in COUNTED.items() if sum(counts[t] for t in play_types) != team_totals[field]]
    points = 2 * counts["2FGM"] + 3 * counts["3FGM"] + counts["FTM"]
    if points != team_totals["Points"]:
        wrong.append("Points")
    return wrong
