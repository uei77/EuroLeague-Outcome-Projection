"""Rebuilds which five players each team had on court, from substitutions."""

from elsim.ingest.parse_pbp import PERIOD_END, flatten

POINTS = {"2FGM": 2, "3FGM": 3, "FTM": 1}


def starters(boxscore: dict) -> dict[str, set[str]]:
    """Return each team's starting five, keyed by team code."""
    result = {}
    for team in boxscore["Stats"]:
        for player in team["PlayersStats"]:
            code = player["Team"].strip()
            result.setdefault(code, set())
            if player["IsStarter"] == 1:
                result[code].add(player["Player_ID"].strip())
    return result


def rebuild(boxscore: dict, playbyplay: dict) -> tuple[list[dict], dict]:
    """Return (stints, report) for one game.

    A stint is a stretch of play in which neither team's five changed. Each
    stint yields one row per team. report counts what went wrong, so a game
    can be excluded from lineup features instead of being silently trusted:
      bad_five_checks      events played while a team did not have exactly five
      bad_substitutions    a player sent off who was not on, or sent on who was
      off_court_events     events credited to a player not on court
    """
    on_court = starters(boxscore)
    teams = list(on_court)
    report = {"bad_five_checks": 0, "bad_substitutions": 0, "off_court_events": 0, "events_checked": 0}
    stints = []

    def open_stint(start: int) -> dict:
        return {
            "start_second": start,
            "fives": {team: frozenset(on_court[team]) for team in teams},
            "points": {team: 0 for team in teams},
        }

    def close_stint(stint: dict, end: int) -> None:
        if end == stint["start_second"] and not any(stint["points"].values()):
            return
        for team in teams:
            other = teams[1 - teams.index(team)]
            stints.append(
                {
                    "stint_number": len(stints) // 2 + 1,
                    "team_code": team,
                    "players": sorted(stint["fives"][team]),
                    "start_second": stint["start_second"],
                    "end_second": end,
                    "points_for": stint["points"][team],
                    "points_against": stint["points"][other],
                    "five_check_passed": len(stint["fives"][team]) == 5,
                }
            )

    current = open_stint(0)
    changed_at = None
    period_end = 0
    for event in flatten(playbyplay):
        elapsed = event["elapsed_seconds"]
        # A few feeds stop before the end-of-game marker, so the last stint is
        # closed at the end of the last period seen, not at the last event.
        period_end = elapsed + event["clock_seconds"]
        team, player, play_type = event["team_code"], event["player_id"], event["play_type"]

        if play_type in ("IN", "OUT"):
            if team not in on_court:
                continue
            if (play_type == "OUT") != (player in on_court[team]):
                report["bad_substitutions"] += 1
            if play_type == "OUT":
                on_court[team].discard(player)
            else:
                on_court[team].add(player)
            if changed_at is None:
                changed_at = elapsed
            continue

        if changed_at is not None:
            close_stint(current, changed_at)
            current = open_stint(changed_at)
            changed_at = None

        if play_type == "BP" or play_type in PERIOD_END:
            continue
        report["events_checked"] += 1
        report["bad_five_checks"] += sum(len(on_court[t]) != 5 for t in teams)
        if player and team in on_court and player not in on_court[team]:
            report["off_court_events"] += 1
        if play_type in POINTS and team in current["points"]:
            current["points"][team] += POINTS[play_type]

    close_stint(current, period_end)
    return stints, report
