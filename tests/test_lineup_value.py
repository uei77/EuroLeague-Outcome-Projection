"""Checks the lineup-based player value on small hand-made stints."""

from elsim.features.lineup_value import fit_values

FIVE = "A|B|C|D|E"
OTHER = "F|G|H|I|J"


def test_player_on_court_for_good_stints_gets_a_higher_value():
    stints = [("S1", FIVE, 300, 12, OTHER, None, None), ("S1", "K|B|C|D|E", 300, -6, OTHER, None, None)] * 50
    values, _ = fit_values(stints, ["S1"])
    assert values["A"] > 0 > values["K"]


def test_a_coach_who_wins_with_two_different_rosters_gets_the_credit():
    # Coach X wins with both fives, coach Y loses with the same players.
    stints = [
        ("S1", FIVE, 300, 10, OTHER, "X", "Z"),
        ("S1", OTHER, 300, 10, FIVE, "X", "Z"),
        ("S1", FIVE, 300, -10, OTHER, "Y", "Z"),
        ("S1", OTHER, 300, -10, FIVE, "Y", "Z"),
    ] * 50
    players, coaches = fit_values(stints, ["S1"])
    assert coaches["X"] > 0 > coaches["Y"]
    assert abs(players["A"]) < coaches["X"]


def test_values_use_only_the_seasons_given():
    stints = [("S1", FIVE, 300, 12, OTHER, None, None), ("S1", "K|B|C|D|E", 300, -6, OTHER, None, None)] * 50
    later = [("S2", "K|B|C|D|E", 300, 40, OTHER, "X", None)] * 50
    assert fit_values(stints + later, ["S1"]) == fit_values(stints, ["S1"])
