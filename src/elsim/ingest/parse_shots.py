"""Turns one raw shots response into field-goal attempts with a court zone.

Coordinates are in centimetres with the basket at (0, 0); x runs across the
court and y away from the baseline. The league also gives each shot a zone
letter: A at the rim, B and C close on the left and right, D and E a step
further, F and G the long two-pointers, H and I the three-pointers, J the
backcourt. Our zones merge left and right, and split three-pointers into
corner and above the break, which the league's letters do not do.
"""

TWO_POINT_ZONES = {
    "A": "rim",
    "B": "paint",
    "C": "paint",
    "D": "short mid-range",
    "E": "short mid-range",
    "F": "long two",
    "G": "long two",
}
ZONES = ["rim", "paint", "short mid-range", "long two", "corner three", "above-break three"]
CORNER_MAX_Y = 150  # the three-point line runs straight along the sideline up to about here


def zone_of(action: str, league_zone: str, y: int) -> str:
    if action.startswith("3"):
        return "corner three" if y < CORNER_MAX_Y else "above-break three"
    # A two-pointer the league filed under a three-point letter was taken with a foot on the line.
    return TWO_POINT_ZONES.get(league_zone, "long two")


def field_goals(shots: dict) -> list[dict]:
    """Return one row per field-goal attempt. Free throws are left out: the
    feed lists only the made ones, and they have no position."""
    rows = []
    for raw in shots["Rows"]:
        action = raw["ID_ACTION"].strip()
        if action not in ("2FGM", "2FGA", "3FGM", "3FGA"):
            continue
        rows.append(
            {
                "shot_number": raw["NUM_ANOT"],
                "team_code": raw["TEAM"].strip(),
                "player_id": raw["ID_PLAYER"].strip(),
                "made": action.endswith("M"),
                "value": int(action[0]),
                "x": raw["COORD_X"],
                "y": raw["COORD_Y"],
                "zone": zone_of(action, raw["ZONE"].strip(), raw["COORD_Y"]),
                "fastbreak": raw["FASTBREAK"] == "1",
                "second_chance": raw["SECOND_CHANCE"] == "1",
                "off_turnover": raw["POINTS_OFF_TURNOVER"] == "1",
            }
        )
    return rows
