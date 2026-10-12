"""Simulates the play-in, the playoffs and the Final Four for many paths at once."""

import numpy as np


class Strengths:
    """One drawn set of team strengths per path, and the chance of a home win
    they imply. net[p, t] is team t's offence minus defence in path p, in
    points per 100 possessions; edge[p] is the home edge."""

    def __init__(self, net: np.ndarray, edge: np.ndarray, noise_sd: float, rng: np.random.Generator):
        self.net, self.edge, self.noise_sd, self.rng = net, edge, noise_sd, rng
        self.paths = np.arange(net.shape[0])

    def home_wins(self, home: np.ndarray, away: np.ndarray, neutral: bool = False) -> np.ndarray:
        """Play one game per path; home and away are team indices per path."""
        mean = self.net[self.paths, home] - self.net[self.paths, away]
        if not neutral:
            mean = mean + self.edge
        return mean + self.noise_sd * self.rng.standard_normal(len(self.paths)) > 0


def play_in(seeds: np.ndarray, strengths: Strengths) -> tuple[np.ndarray, np.ndarray]:
    """seeds[p] holds the teams placed 7th to 10th. Return the teams seeded
    7th and 8th for the playoffs."""
    seventh, eighth, ninth, tenth = seeds.T
    first = strengths.home_wins(seventh, eighth)
    second = strengths.home_wins(ninth, tenth)
    seed_seven = np.where(first, seventh, eighth)
    loser_first = np.where(first, eighth, seventh)
    winner_second = np.where(second, ninth, tenth)
    seed_eight = np.where(strengths.home_wins(loser_first, winner_second), loser_first, winner_second)
    return seed_seven, seed_eight


def series(high: np.ndarray, low: np.ndarray, strengths: Strengths, home_pattern: list[bool]) -> np.ndarray:
    """Best-of-len(home_pattern) series; high has home-court advantage.
    All games are drawn; whoever wins the majority wins the series, which is
    the same as stopping at the deciding win."""
    high_wins = np.zeros(len(high), dtype=int)
    for at_high in home_pattern:
        if at_high:
            high_wins += strengths.home_wins(high, low)
        else:
            high_wins += ~strengths.home_wins(low, high)
    return np.where(high_wins > len(home_pattern) // 2, high, low)


def knockout(top_eight: np.ndarray, strengths: Strengths, config: dict) -> tuple[np.ndarray, np.ndarray]:
    """top_eight[p] holds seeds 1 to 8. Return (Final Four teams [p, 4], champion [p])."""
    winners = [series(top_eight[:, i], top_eight[:, 7 - i], strengths, config["series_home_pattern"]) for i in range(4)]
    finalists = []
    for a, b in config["final_four_semi_finals"]:
        finalists.append(np.where(strengths.home_wins(winners[a], winners[b], neutral=True), winners[a], winners[b]))
    champion = np.where(strengths.home_wins(finalists[0], finalists[1], neutral=True), finalists[0], finalists[1])
    return np.stack(winners, axis=1), champion
