"""Compares our pre-game probabilities with the market's on finished games."""

from math import log


def _loss(p: float, home_won: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -log(p if home_won else 1 - p)


def summarise(rows: list[dict]) -> list[dict]:
    """Return one line per round and a final "all" line: games, and the log
    loss (lower is better) of our forecast, our forecast with known absences,
    and the market. rows come from queries.track_record."""
    groups = [(str(r), [g for g in rows if g["round"] == r]) for r in sorted({g["round"] for g in rows})]
    groups.append(("all", rows))
    mean = lambda group, key: sum(_loss(g[key], g["home_won"]) for g in group) / len(group)
    return [
        {
            "round": name,
            "games": len(group),
            "model": mean(group, "p_model"),
            "model_with_absences": mean(group, "p_model_with_absences"),
            "market": mean(group, "p_market"),
        }
        for name, group in groups
        if group
    ]


def closing_line_value(rows: list[dict]) -> dict | None:
    """How the market moved between our two snapshots, measured from where we
    stood at the first one. For games with both snapshots and a forecast made
    before the first: lean is our forecast minus the opening market, move is
    the closing market minus the opening market. If the market moves towards
    us more often than away, we saw something it had not priced yet.

    Returns games, the share of moving games that moved our way, and the
    average move in our direction (probability points), or None without data.
    """
    pairs = [
        (g["p_model_at_open"] - g["p_open"], g["p_market"] - g["p_open"])
        for g in rows
        if g.get("p_open") is not None and g.get("p_model_at_open") is not None
    ]
    moving = [(lean, move) for lean, move in pairs if lean != 0 and abs(move) > 1e-6]
    if not moving:
        return None
    toward = sum((lean > 0) == (move > 0) for lean, move in moving)
    return {
        "games": len(pairs),
        "moving": len(moving),
        "share_toward_us": toward / len(moving),
        "average_move_toward_us": sum(move if lean > 0 else -move for lean, move in moving) / len(moving),
    }
