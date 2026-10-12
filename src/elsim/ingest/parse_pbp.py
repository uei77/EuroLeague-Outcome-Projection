"""Turns one raw play-by-play response into a flat, ordered list of events."""

REGULATION_PERIODS = ["FirstQuarter", "SecondQuarter", "ThirdQuarter", "ForthQuarter"]
QUARTER_SECONDS = 600
OVERTIME_SECONDS = 300
# "EP" ends a period; the last period of a game ends with "EG" instead.
PERIOD_END = ("EP", "EG")


def _clock_seconds(marker: str) -> int | None:
    """Seconds left in the period, or None when the marker is empty or broken
    (the feed contains a few such as "-1:00")."""
    if ":" not in marker:
        return None
    minutes, seconds = marker.split(":")
    value = int(minutes) * 60 + int(seconds)
    return value if value >= 0 else None


def flatten(playbyplay: dict) -> list[dict]:
    """Return events in playing order with period, clock and elapsed game time.

    period is 1 to 4 for quarters and 5 upwards for overtime periods. An event
    with no usable clock keeps the clock of the event before it. Overtime
    periods all arrive in one list; a new one starts at the first event after
    an end-of-period marker. Substitutions often come before the "BP" (begin
    period) event, so "BP" cannot be used to count periods.
    """
    events = []
    period = 0
    period_start = 0
    period_length = QUARTER_SECONDS

    def start_period(length: int) -> None:
        nonlocal period, period_start, period_length, clock
        period_start += period_length if period else 0
        period += 1
        period_length = length
        clock = length

    clock = QUARTER_SECONDS
    for name in REGULATION_PERIODS + ["ExtraTime"]:
        raw_events = playbyplay.get(name) or []
        overtime = name == "ExtraTime"
        if raw_events and not overtime:
            start_period(QUARTER_SECONDS)
        period_open = False
        for raw in raw_events:
            play_type = raw["PLAYTYPE"].strip()
            if overtime and not period_open and play_type not in PERIOD_END:
                start_period(OVERTIME_SECONDS)
                period_open = True
            marked = _clock_seconds(raw.get("MARKERTIME") or "")
            if play_type in PERIOD_END:
                clock = 0
                period_open = False
            elif marked is not None:
                clock = min(clock, marked)
            events.append(
                {
                    "play_number": raw["NUMBEROFPLAY"],
                    "period": period,
                    "clock_seconds": clock,
                    "elapsed_seconds": period_start + period_length - clock,
                    "team_code": (raw.get("CODETEAM") or "").strip(),
                    "player_id": (raw.get("PLAYER_ID") or "").strip(),
                    "play_type": play_type,
                    "points_home": raw.get("POINTS_A"),
                    "points_away": raw.get("POINTS_B"),
                }
            )
    return events
