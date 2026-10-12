"""Calibration of home-win probabilities: of the games given about x%, how
many did the home team win? A table for reading and a chart for looking."""

from math import sqrt

BIN_EDGES = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
MIN_GAMES = 20  # bins with fewer games are too noisy to show

# Colours from the project's chart palette, validated for colour-blind
# separation on the light surface. The third is pale against the surface,
# so every series is also labelled directly on the chart.
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = [
    ("p_roster", "Rating model with roster start", "#2a78d6"),
    ("p_rating", "Rating model alone", "#eb6834"),
    ("p_constant", "Constant home-win rate", "#1baf7a"),
]


def table(rows: list[dict], model: str) -> list[tuple]:
    """Return (low, high, games, mean forecast, actual rate, low 95%, high 95%)
    per bin. The interval is the Wilson interval for the actual rate."""
    out = []
    for low, high in zip(BIN_EDGES, BIN_EDGES[1:]):
        group = [r for r in rows if low <= r[model] < high or (high == 1.0 and r[model] == 1.0)]
        if len(group) < MIN_GAMES:
            continue
        n = len(group)
        rate = sum(r["home_won"] for r in group) / n
        z = 1.96
        centre = (rate + z * z / (2 * n)) / (1 + z * z / n)
        half = z * sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        out.append((low, high, n, sum(r[model] for r in group) / n, rate, centre - half, centre + half))
    return out


CONFIDENCE_LEVELS = (0.60, 0.65, 0.70, 0.75, 0.80)
CONFIDENCE_FILE = "reports/confidence.csv"


def confidence(rows: list[dict], model: str) -> list[tuple]:
    """Return (level, share of games, games, favourite won, model expected)
    for the games where the favourite was given at least each level."""
    out = []
    for level in CONFIDENCE_LEVELS:
        group = [r for r in rows if max(r[model], 1 - r[model]) >= level]
        if not group:
            continue
        won = sum((r[model] > 0.5) == bool(r["home_won"]) for r in group) / len(group)
        expected = sum(max(r[model], 1 - r[model]) for r in group) / len(group)
        out.append((level, len(group) / len(rows), len(group), won, expected))
    return out


def save_confidence(rows: list[dict], model: str, path: str = CONFIDENCE_FILE) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["level", "share_of_games", "games", "favourite_won", "model_expected"])
        writer.writerows(confidence(rows, model))


def plot(rows: list[dict], path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7.2, 6.4), dpi=150)
    figure.patch.set_facecolor(SURFACE)
    axis.set_facecolor(SURFACE)
    axis.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle=(0, (4, 4)), zorder=1)
    axis.annotate(
        "perfect calibration",
        xy=(0.11, 0.11),
        xytext=(0.15, 0.075),
        color=MUTED,
        fontsize=9,
        va="center",
        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8},
    )

    # Where each series is named on the chart: (point index, text position).
    labels = {"p_roster": (-1, (0.60, 0.93)), "p_rating": (-1, (0.87, 0.80)), "p_constant": (-1, (0.70, 0.52))}
    for order, (model, label, colour) in enumerate(SERIES):
        bins = table(rows, model)
        x, y = [b[3] for b in bins], [b[4] for b in bins]
        if order == 0:  # the published model also shows how uncertain each point is
            axis.errorbar(
                x,
                y,
                yerr=[[b[4] - b[5] for b in bins], [b[6] - b[4] for b in bins]],
                fmt="none",
                ecolor=colour,
                elinewidth=1.2,
                capsize=3,
                alpha=0.55,
                zorder=2,
            )
        constant = model == "p_constant"  # a constant forecast is a point, not a curve
        axis.plot(
            x,
            y,
            color=colour,
            linewidth=0 if constant else 2,
            marker="D" if constant else "o",
            markersize=9 if constant else 7,
            markeredgecolor=SURFACE,
            markeredgewidth=2,
            label=label,
            zorder=6 if constant else 5 - order,
        )
        point, position = labels[model]
        axis.annotate(
            label,
            xy=(x[point], y[point]),
            xytext=position,
            color=INK,
            fontsize=9,
            va="center",
            arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8, "shrinkB": 6},
        )

    games = len(rows)
    seasons = sorted({r["season_code"] for r in rows})
    axis.set_title(
        f"Are the forecasts honest?  {games:,} out-of-sample games, {seasons[0]} to {seasons[-1]}",
        loc="left",
        color=INK,
        fontsize=12,
        pad=14,
    )
    axis.set_xlabel("Forecast probability that the home team wins", color=MUTED, fontsize=10)
    axis.set_ylabel("Share of those games the home team won", color=MUTED, fontsize=10)
    axis.set_xlim(0.05, 1.0)
    axis.set_ylim(0.05, 1.0)
    axis.set_aspect("equal")
    ticks = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    axis.set_xticks(ticks, [f"{t:.0%}" for t in ticks])
    axis.set_yticks(ticks, [f"{t:.0%}" for t in ticks])
    axis.tick_params(colors=MUTED, labelsize=9, length=0)
    axis.grid(color=GRID, linewidth=0.8)
    axis.set_axisbelow(True)
    for spine in axis.spines.values():
        spine.set_visible(False)
    axis.legend(loc="upper left", frameon=False, fontsize=9, labelcolor=INK)
    figure.text(
        0.125,
        0.015,
        "Bars: 95% interval for the published model. Bins with fewer than 20 games are not shown.",
        color=MUTED,
        fontsize=8,
    )
    figure.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(figure)
