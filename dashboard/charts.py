"""The dashboard's charts."""

from math import asin, cos, pi, sin, sqrt

import altair as alt
import pandas as pd

# Colours validated for colour-blind separation on the light surface. The
# third is pale against it, so the parts are also named in the legend and in
# every tooltip, and the same numbers stand in the table above the chart.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
PART_LABELS = {"minutes_form": "Minutes form", "rate_form": "Rate form", "matchup": "Matchup"}
OUTCOMES = {"p_title": "Title", "p_final_four": "Final Four", "p_playoffs": "Playoffs", "p_play_in": "Play-in"}


def lift_chart(rising: pd.DataFrame) -> alt.Chart:
    """Stacked bars: how much each part adds to (or takes from) each listed player's lift."""
    parts = rising.melt(
        id_vars=["player_name", "rank", "lift"], value_vars=list(PART_LABELS), var_name="part", value_name="valuation"
    )
    parts["stack_order"] = parts["part"].map({key: i for i, key in enumerate(PART_LABELS)})
    parts["part"] = parts["part"].map(PART_LABELS)
    return (
        alt.Chart(parts, title="Where each player's lift comes from")
        .mark_bar(size=14)
        .encode(
            y=alt.Y(
                "player_name:N",
                sort=alt.EncodingSortField("rank", order="ascending"),
                title=None,
                axis=alt.Axis(labelLimit=220),
            ),
            x=alt.X("valuation:Q", title="Valuation points above his own norm"),
            color=alt.Color(
                "part:N",
                title=None,
                sort=list(PART_LABELS.values()),
                scale=alt.Scale(domain=list(PART_LABELS.values()), range=[BLUE, ORANGE, AQUA]),
                legend=alt.Legend(orient="top"),
            ),
            order=alt.Order("stack_order:Q"),
            tooltip=[
                alt.Tooltip("player_name:N", title="Player"),
                alt.Tooltip("part:N", title="Part"),
                alt.Tooltip("valuation:Q", title="Valuation", format="+.2f"),
                alt.Tooltip("lift:Q", title="Total lift", format="+.2f"),
            ],
        )
        .properties(height=340)
    )


def season_chart(result: pd.DataFrame, outcome: str) -> alt.Chart:
    """One bar per team: its chance of the chosen outcome, highest first."""
    return (
        alt.Chart(result, title=f"Chance of: {OUTCOMES[outcome]}")
        .mark_bar(size=14, color=BLUE)
        .encode(
            y=alt.Y("team_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X(f"{outcome}:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            tooltip=[
                alt.Tooltip("team_name:N", title="Team"),
                alt.Tooltip("expected_wins:Q", title="Expected wins", format=".1f"),
                *(alt.Tooltip(f"{key}:Q", title=label, format=".1%") for key, label in OUTCOMES.items()),
            ],
        )
        .properties(height=520)
    )


FEW_SHOTS = 20
ZONE_ORDER = ["rim", "paint", "short mid-range", "long two", "corner three", "above-break three"]


def zones_chart(team: pd.DataFrame) -> alt.Chart:
    """One bar per zone: points per shot a team allows there, minus the
    league's. To the right means it concedes more than the league."""
    data = team.assign(difference=team["points_per_shot"] - team["league_points_per_shot"])
    data["side"] = data["difference"].map(
        lambda d: "Allows more than the league" if d > 0 else "Allows less than the league"
    )
    sides = ["Allows more than the league", "Allows less than the league"]
    data["sample"] = data["attempts"].map(lambda n: "20 shots or more" if n >= FEW_SHOTS else "fewer than 20 shots")
    bars = (
        alt.Chart(data, title="Points per shot allowed, against the league")
        .mark_bar(size=18)
        .encode(
            y=alt.Y("zone:N", sort=ZONE_ORDER, title=None),
            x=alt.X("difference:Q", title="Points per shot, team minus league", axis=alt.Axis(format="+.2f")),
            color=alt.Color(
                "side:N",
                title=None,
                scale=alt.Scale(domain=sides, range=[ORANGE, BLUE]),
                legend=alt.Legend(orient="top"),
            ),
            # A zone with few shots says little: its bar is faded.
            opacity=alt.Opacity(
                "sample:N",
                title=None,
                legend=alt.Legend(orient="top"),
                scale=alt.Scale(domain=["20 shots or more", "fewer than 20 shots"], range=[1.0, 0.3]),
            ),
            tooltip=[
                alt.Tooltip("zone:N", title="Zone"),
                alt.Tooltip("attempts:Q", title="Shots faced"),
                alt.Tooltip("points_per_shot:Q", title="Allowed per shot", format=".2f"),
                alt.Tooltip("league_points_per_shot:Q", title="League per shot", format=".2f"),
                alt.Tooltip("share_of_attempts:Q", title="Share of shots faced", format=".0%"),
                alt.Tooltip("league_share_of_attempts:Q", title="League share", format=".0%"),
            ],
        )
    )
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#52514e").encode(x="x:Q")
    return (bars + zero).properties(height=260)


def _court_lines() -> pd.DataFrame:
    """Half-court markings in centimetres, basket at (0, 0): baseline and
    sidelines, the paint, the three-point line and the rim."""
    baseline, half_width = -157.5, 750.0
    corner_x, arc_radius = 660.0, 675.0
    corner_y = sqrt(arc_radius**2 - corner_x**2)
    corner_angle = asin(corner_y / arc_radius)  # where the arc meets the straight corner line
    paths = {
        "boundary": [(-half_width, 900), (-half_width, baseline), (half_width, baseline), (half_width, 900)],
        "paint": [(-245, baseline), (-245, baseline + 580), (245, baseline + 580), (245, baseline)],
        "three": [(-corner_x, baseline), (-corner_x, corner_y)]
        + [
            (arc_radius * cos(angle), arc_radius * sin(angle))
            for angle in (corner_angle + i * (pi - 2 * corner_angle) / 60 for i in range(60, -1, -1))
        ]
        + [(corner_x, corner_y), (corner_x, baseline)],
        "rim": [(22.5 * cos(2 * pi * i / 24), 22.5 * sin(2 * pi * i / 24)) for i in range(25)],
    }
    return pd.DataFrame(
        [
            {"line": name, "order": i, "x": x, "y": y}
            for name, points in paths.items()
            for i, (x, y) in enumerate(points)
        ]
    )


def shot_chart(shots: pd.DataFrame, title: str) -> alt.Chart:
    """Where a player has shot from this season. Made and missed differ in
    colour and in shape, so the chart also reads without colour."""
    court = (
        alt.Chart(_court_lines())
        .mark_line(color="#b9b8b2", strokeWidth=1.5)
        .encode(
            x=alt.X("x:Q", scale=alt.Scale(domain=[-780, 780]), axis=None),
            y=alt.Y("y:Q", scale=alt.Scale(domain=[-190, 950]), axis=None),  # shots from further out are not drawn
            detail="line:N",
            order="order:Q",
        )
    )
    data = shots.assign(result=shots["made"].map({True: "Made", False: "Missed"}))
    points = (
        alt.Chart(data)
        .mark_point(size=55, filled=True, opacity=0.8, clip=True)
        .encode(
            x="x:Q",
            y="y:Q",
            color=alt.Color(
                "result:N",
                title=None,
                scale=alt.Scale(domain=["Made", "Missed"], range=[BLUE, ORANGE]),
                legend=alt.Legend(orient="top"),
            ),
            shape=alt.Shape(
                "result:N", scale=alt.Scale(domain=["Made", "Missed"], range=["circle", "cross"]), legend=None
            ),
            tooltip=[
                alt.Tooltip("result:N", title="Result"),
                alt.Tooltip("zone:N", title="Zone"),
                alt.Tooltip("value:Q", title="Worth"),
            ],
        )
    )
    return (court + points).properties(title=title, width=520, height=380)
