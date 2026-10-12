"""Plain-text forecast files, one block per game: games.txt (every unplayed
game of the season) and players.txt (each team's expected top performers in
the coming rounds' games). Written by `predict` next to its stored run."""

from datetime import timedelta, timezone
from pathlib import Path

Z80 = 1.2816  # half-width of a central 80% range, in standard deviations
PLAYERS_PER_TEAM = 5


def _local(t) -> str:
    return t.replace(tzinfo=timezone.utc).astimezone().strftime("%a %d %b %Y, %H:%M")


def _game_block(r: dict, teams: dict, market: dict) -> list[str]:
    home, away = teams.get(r["home_code"], r["home_code"]), teams.get(r["away_code"], r["away_code"])
    margin, spread = r["expected_margin"], Z80 * r["margin_sd"]
    total, total_spread = r["home_points"] + r["away_points"], Z80 * r["total_sd"]
    favourite = home if r["p_home"] >= 0.5 else away
    lines = [
        f"{_local(r['tipoff_utc'])}  |  round {r['round']}",
        f"{home} ({r['home_code']}) v {away} ({r['away_code']})",
        f"  Win chance        {r['home_code']} {r['p_home']:.1%}   {r['away_code']} {1 - r['p_home']:.1%}"
        f"   (favourite: {favourite}{', confident pick' if max(r['p_home'], 1 - r['p_home']) >= 0.65 else ''})",
        f"  Expected score    {r['home_points']:.0f} - {r['away_points']:.0f}",
        f"  Margin (home)     {margin:+.1f}, 80% range {margin - spread:+.0f} to {margin + spread:+.0f}",
        f"  Total points      {total:.0f}, 80% range {total - total_spread:.0f} to {total + total_spread:.0f}",
    ]
    if abs(r["absence_shift"]) > 1e-9:
        lines.append(f"  With known absences  {r['home_code']} {r['p_home_with_absences']:.1%}")
    p_market, books = market.get(r["game_code"], (None, 0))
    if p_market is not None:
        lines.append(
            f"  Market            {r['home_code']} {p_market:.1%} (median of {books} bookmakers, comparison only)"
        )
    return lines


def _player_lines(players: list[dict]) -> list[str]:
    lines = []
    for rank, p in enumerate(sorted(players, key=lambda x: -x["score"])[:PLAYERS_PER_TEAM], start=1):
        flag = "  rising" if p.get("rising") else ""
        lines.append(
            f"    {rank}. {p['player_name'][:26]:<27}{p['position']:<8} "
            f"{p['expected_seconds'] / 60:>4.0f} min   expected PIR {p['score']:>5.1f}   "
            f"vs own norm {p['lift']:+.1f}{flag}"
        )
    return lines


def write_reports(
    out_dir: Path,
    run_id: str,
    games: list[dict],
    candidates: list[dict],
    market: dict,
    teams: dict,
    absent_names: list[str],
    player_rounds: list[int],
    rising_ids: set[tuple[str, int]],
) -> tuple[Path, Path]:
    """Write games.txt and players.txt into out_dir and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    games = sorted(games, key=lambda r: (r["tipoff_utc"], r["game_code"]))
    header = [
        f"EuroLeague forecasts, run {run_id} (times in this computer's local time)",
        "Probabilities come from the published model; ranges are 80% ranges. No betting advice.",
        "Known absences: " + ("; ".join(absent_names) if absent_names else "none entered"),
        "",
    ]
    game_lines = header + [f"{len(games)} games to come, in playing order", ""]
    for r in games:
        game_lines += _game_block(r, teams, market) + [""]
    games_path = out_dir / "games.txt"
    games_path.write_text("\n".join(game_lines), encoding="utf-8")

    scored = [c for c in candidates if not c["game_played"] and not c.get("absent") and "score" in c]
    player_lines = header + [
        f"Expected top performers per team, rounds {', '.join(map(str, player_rounds))}",
        "Expected PIR is the league's valuation the player is expected to post; 'vs own norm' is the form and",
        "matchup part of it; 'rising' marks the rotation players most likely to beat their own norm.",
        "Later rounds are not listed: who plays and in what form is not known that far ahead.",
        "",
    ]
    for r in (g for g in games if g["round"] in player_rounds):
        in_game = [c for c in scored if c["game_code"] == r["game_code"]]
        player_lines += _game_block(r, teams, market)[:2]
        for code in (r["home_code"], r["away_code"]):
            team_players = [
                {**c, "rising": (c["player_id"], c["game_code"]) in rising_ids}
                for c in in_game
                if c["team_code"] == code
            ]
            player_lines.append(f"  {teams.get(code, code)}")
            player_lines += _player_lines(team_players) or ["    no players expected"]
        player_lines.append("")
    players_path = out_dir / "players.txt"
    players_path.write_text("\n".join(player_lines), encoding="utf-8")
    return games_path, players_path


WEEK_DAYS = 6  # a matchweek: the rounds whose games all tip off within 6 days of the first one


def matchweek(games: list[dict]) -> list[int]:
    """The rounds of the coming matchweek: one round, or two in a double-round week."""
    if not games:
        return []
    start = min(r["tipoff_utc"] for r in games)
    rounds = sorted({r["round"] for r in games})
    return [
        n for n in rounds if max(r["tipoff_utc"] for r in games if r["round"] == n) <= start + timedelta(days=WEEK_DAYS)
    ]


def week_label(rounds: list[int]) -> str:
    return "round-" + "-".join(f"{n:02d}" for n in rounds)
