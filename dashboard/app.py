"""Dashboard over the latest model run.

Run from the project root:  streamlit run dashboard/app.py
It reads the database through the same functions as the API.
"""

import json
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from charts import OUTCOMES, ZONE_ORDER, lift_chart, season_chart, shot_chart, zones_chart
from elsim import settings as settings_module
from elsim.api import queries
from elsim.models.calibration import CONFIDENCE_FILE
from elsim.models.market import summarise

CONFIDENT = 0.65  # forecasts this sure are marked as confident picks

st.set_page_config(page_title="EuroLeague forecasts", layout="wide")
settings = settings_module.load()
season = settings["current_season"]
with duckdb.connect(settings["db_path"], read_only=True) as db:
    if not queries.has_run(db):
        st.title("EuroLeague forecasts")
        st.info("No forecast is stored yet. Run: python -m elsim.cli round")
        st.stop()
    run = queries.latest_run(db)
    games = pd.DataFrame(queries.games(db, run["run_id"], season))
    players = pd.DataFrame(queries.players(db, run["run_id"]))
    simulation = pd.DataFrame(queries.simulation(db, run["run_id"], season))
    absences = pd.DataFrame(queries.absences(db, run["run_id"], season))
    record = queries.track_record(db, season)
    zones = pd.DataFrame(queries.zones_allowed(db, season))
    shooters = queries.shooters(db, season)
    explained = queries.explanations(db, run["run_id"])
model = json.loads(run["parameters"])

st.title("EuroLeague forecasts")
st.caption(
    f"Run {run['run_id']} · data through {run['data_through_utc']:%d %B %Y} · {model['model']} · "
    f"seed {run['seed']} · code {run['git_sha'][:8] if run['git_sha'] else 'not under version control'}"
)
if absences.empty:
    st.warning("No absences were entered for this run. Every forecast assumes each team's recent rotation plays.")
else:
    listed = "; ".join(f"{a.player_name} ({a.team_code}, until {a.until:%d %b %Y})" for a in absences.itertuples())
    st.info(
        f"Known absences entered by hand: {listed}. Any other absence is unknown: "
        "forecasts assume each team's recent rotation plays."
    )

tab_names = ["Games", "Players to Watch", "Season", "Track record"] + (["Shots"] if shooters else [])
games_tab, players_tab, season_tab, record_tab, *shot_tabs = st.tabs(tab_names)

with games_tab:
    for round_number, in_round in games.groupby("round"):
        st.subheader(f"Round {round_number}")
        table = pd.DataFrame(
            {
                "Tip-off (UTC)": in_round["tipoff_utc"].dt.strftime("%a %d %b %H:%M"),
                "Home": in_round["home_name"],
                "Away": in_round["away_name"],
                "Home win": in_round["p_home"],
                "Expected score": in_round["home_points"].round().astype("Int64").astype(str)
                + " - "
                + in_round["away_points"].round().astype("Int64").astype(str),
                "Expected margin": in_round["expected_margin"],
                "Home win, with absences": in_round["p_home_with_absences"].where(in_round["has_absences"]),
                "Market": in_round["p_market"],
                "Bookmakers": in_round["bookmakers"],
                "Confident pick": in_round["home_name"].where(
                    in_round["p_home"] >= CONFIDENT, in_round["away_name"].where(in_round["p_home"] <= 1 - CONFIDENT)
                ),
            }
        )
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "Home win": st.column_config.ProgressColumn(format="%.3f", min_value=0, max_value=1),
                "Expected score": st.column_config.TextColumn(
                    help="Expected points, home - away, at the two teams' average pace this season. On past seasons each team's score was off by about 8 points on average."
                ),
                "Expected margin": st.column_config.NumberColumn(
                    format="%+.1f",
                    help="Points, home minus away. One game's margin has a standard deviation of about 12 to 13 points.",
                ),
                "Home win, with absences": st.column_config.NumberColumn(
                    format="%.3f", help="Shown only where a known absence changes the forecast."
                ),
                "Market": st.column_config.NumberColumn(
                    format="%.3f",
                    help="Median bookmaker, each with its own margin removed, from the latest odds snapshot.",
                ),
                "Confident pick": st.column_config.TextColumn(
                    help=f"The favourite, where the model gives it {CONFIDENT:.0%} or more."
                ),
            },
        )
    st.caption(
        "Home win is the published model's probability. The market column is for comparison only; "
        "this project gives no betting advice."
    )

    if Path(CONFIDENCE_FILE).exists():
        st.subheader("How often the favourite wins")
        bands = pd.read_csv(CONFIDENCE_FILE)
        st.dataframe(
            pd.DataFrame(
                {
                    "Favourite given at least": bands["level"],
                    "Share of games": bands["share_of_games"],
                    "Games": bands["games"],
                    "Favourite won": bands["favourite_won"],
                    "Model expected": bands["model_expected"],
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Favourite given at least": st.column_config.NumberColumn(format="percent"),
                "Share of games": st.column_config.NumberColumn(format="percent"),
                "Favourite won": st.column_config.NumberColumn(format="percent"),
                "Model expected": st.column_config.NumberColumn(format="percent"),
            },
        )
        st.caption(
            "Past seasons, forecast without seeing them (walk-forward; `backtest` rewrites this table). "
            "Over all games the model picks about 65.5% of winners; even perfect knowledge of team strength "
            "would give only about 67-70%, because one game's luck outweighs most differences. Higher accuracy "
            "exists only on the confident games, and they are a minority."
        )

    if explained["games"]:
        st.subheader("Why this forecast")
        parts = pd.DataFrame(explained["games"])
        shown = games.assign(label=games["home_name"] + " v " + games["away_name"])
        choice = st.selectbox("Game", shown["game_code"], format_func=dict(zip(shown["game_code"], shown["label"])).get)
        game_parts = parts[parts["game_code"] == choice]
        used, left_out = game_parts[game_parts["in_forecast"]], game_parts[~game_parts["in_forecast"]]
        points = st.column_config.NumberColumn(format="%+.2f", help="Points, home minus away.")
        st.markdown("**In the forecast.** These parts add up to the expected margin.")
        st.dataframe(
            used[["label", "points"]].rename(columns={"label": "Part", "points": "Points"}),
            hide_index=True,
            width="stretch",
            column_config={"Points": points},
        )
        factors = pd.DataFrame(explained["factors"]).set_index("factor")
        left_out = left_out.assign(
            typical=left_out["part"].map(factors["effect_per_100"] * factors["typical_difference"]),
            uncertainty=left_out["part"].map(factors["se"] * factors["typical_difference"]),
        )
        st.markdown("**Not in the forecast.** What each would add to this game if it were used.")
        st.dataframe(
            left_out[["label", "points", "typical", "uncertainty"]].rename(
                columns={
                    "label": "Factor",
                    "points": "Would add (points)",
                    "typical": "Typical size",
                    "uncertainty": "±",
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Would add (points)": points,
                "Typical size": st.column_config.NumberColumn(
                    format="%+.2f",
                    help="What a typical difference between two teams has been worth beyond the forecast on past games, points per 100 possessions.",
                ),
                "±": st.column_config.NumberColumn(format="%.2f", help="Standard error of the typical size."),
            },
        )
        st.caption(
            "The left-out factors are measured on how far past games ended from this model's forecast, over "
            "all seasons at once. Each was tried as part of the forecast, predicting seasons it had not seen, "
            "and none made the forecasts better, so they are shown and never added. Sizes within about two "
            "standard errors of zero can be chance; hand-entered absences count only in the forecast with absences."
        )

with players_tab:
    round_number = st.selectbox("Round", sorted(players["round"].unique()))
    in_round = players[players["round"] == round_number]
    if round_number <= 6:
        st.warning("Early season: on past seasons the second list showed no edge in rounds 1 to 6.")
    columns = {
        "rank": "#",
        "player_name": "Player",
        "team_code": "Team",
        "opponent_code": "Against",
        "position": "Position",
        "expected_minutes": "Minutes",
        "score": "Score",
        "lift": "Lift",
        "level": "Level",
        "minutes_form": "Minutes form",
        "rate_form": "Rate form",
        "matchup": "Matchup",
        "team": "Team scoring",
    }
    number = st.column_config.NumberColumn(format="%+.1f")
    plain = st.column_config.NumberColumn(format="%.1f")
    config = {
        "Minutes": plain,
        "Score": plain,
        "Level": plain,
        "Lift": number,
        "Minutes form": number,
        "Rate form": number,
        "Matchup": number,
        "Team scoring": number,
    }

    st.subheader("Expected to produce most")
    st.caption(
        "Ranked by score, in valuation (PIR). On 178 past rounds this list was no better than "
        "simply taking the ten highest season averages. It shows who the best players are, and why."
    )
    top = in_round[in_round["list"] == "top"]
    st.dataframe(top[list(columns)].rename(columns=columns), hide_index=True, width="stretch", column_config=config)

    st.subheader("Expected to beat their own norm")
    st.caption(
        "Rotation players ranked by lift: the form and matchup parts of the score. On past rounds the "
        "listed players beat their own season average by 0.76 when they played, against 0.10 for "
        "rotation players in general."
    )
    rising = in_round[in_round["list"] == "rising"]
    st.dataframe(rising[list(columns)].rename(columns=columns), hide_index=True, width="stretch", column_config=config)

    st.altair_chart(lift_chart(rising), width="stretch")
    st.caption(
        "Matchup is by position (guard, forward, center), not by court zone. "
        "A listed player may not play: availability is known only from the absences above."
    )

with season_tab:
    if simulation.empty:
        st.info("No simulation is stored for this run yet. Run: python -m elsim.cli simulate")
    else:
        scenarios = {"baseline": "Without known absences", "with_absences": "With known absences (hand-entered)"}
        available = [s for s in scenarios if s in set(simulation["scenario"])]
        scenario = st.radio("Scenario", available, format_func=scenarios.get, index=len(available) - 1, horizontal=True)
        result = simulation[simulation["scenario"] == scenario]
        st.caption(
            f"{int(result['n_paths'].iloc[0]):,} simulated seasons, seed {run['seed']}. Each path draws every "
            "team's strength from what the model currently believes and keeps it for the season. Checked on "
            "five past seasons, stated chances of a top-eight finish matched what happened. Title and "
            "Final Four chances cannot be checked that way."
        )
        outcome = st.radio("Chart", list(OUTCOMES), format_func=OUTCOMES.get, index=2, horizontal=True)
        st.altair_chart(season_chart(result, outcome), width="stretch")
        table = result[["team_name", "expected_wins", "p_play_in", "p_playoffs", "p_final_four", "p_title"]].rename(
            columns={
                "team_name": "Team",
                "expected_wins": "Expected wins",
                "p_play_in": "Play-in",
                "p_playoffs": "Playoffs",
                "p_final_four": "Final Four",
                "p_title": "Title",
            }
        )
        for column in ("Play-in", "Playoffs", "Final Four", "Title"):
            table[column] = table[column] * 100
        percent = st.column_config.NumberColumn(format="%.1f%%")
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "Expected wins": st.column_config.NumberColumn(format="%.1f"),
                "Play-in": percent,
                "Playoffs": percent,
                "Final Four": percent,
                "Title": percent,
            },
        )

with record_tab:
    st.caption(
        "Finished games for which a forecast and an odds snapshot both existed before tip-off. "
        "Log loss, lower is better. The market knows injuries and news that this model does not."
    )
    if not record:
        st.info(
            "No finished game yet has both a stored forecast and an odds snapshot from before its tip-off. "
            "The first lines appear after the next round."
        )
    else:
        summary = pd.DataFrame(summarise(record)).rename(
            columns={
                "round": "Round",
                "games": "Games",
                "model": "Model",
                "model_with_absences": "Model, with absences",
                "market": "Market",
            }
        )
        loss = st.column_config.NumberColumn(format="%.4f")
        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
            column_config={"Model": loss, "Model, with absences": loss, "Market": loss},
        )
        st.caption("A handful of games says little: the difference only means something over many rounds.")
        games_played = pd.DataFrame(record)
        st.dataframe(
            pd.DataFrame(
                {
                    "Round": games_played["round"],
                    "Home": games_played["home_code"],
                    "Away": games_played["away_code"],
                    "Home won": games_played["home_won"],
                    "Model": games_played["p_model"],
                    "Model, with absences": games_played["p_model_with_absences"],
                    "Market": games_played["p_market"],
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Model": st.column_config.NumberColumn(format="%.3f"),
                "Model, with absences": st.column_config.NumberColumn(format="%.3f"),
                "Market": st.column_config.NumberColumn(format="%.3f"),
            },
        )

if shot_tabs:
    with shot_tabs[0]:
        st.caption(
            "From the shot data, this season so far. These pages describe; they do not feed the forecasts. "
            "A zone-based matchup was measured against the position-based one and added nothing, "
            "so Players to Watch stays position-based."
        )
        left, right = st.columns(2)
        with left:
            st.subheader("What a team allows, by zone")
            team_name = st.selectbox("Team", sorted(zones["team_name"].unique()))
            team = zones[zones["team_name"] == team_name]
            st.altair_chart(zones_chart(team), width="stretch")
            table = team.set_index("zone").loc[[z for z in ZONE_ORDER if z in set(team["zone"])]].reset_index()
            st.dataframe(
                pd.DataFrame(
                    {
                        "Zone": table["zone"],
                        "Shots faced": table["attempts"],
                        "Share of shots": table["share_of_attempts"] * 100,
                        "League share": table["league_share_of_attempts"] * 100,
                        "Points per shot": table["points_per_shot"],
                        "League": table["league_points_per_shot"],
                    }
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    "Share of shots": st.column_config.NumberColumn(format="%.0f%%"),
                    "League share": st.column_config.NumberColumn(format="%.0f%%"),
                    "Points per shot": st.column_config.NumberColumn(format="%.2f"),
                    "League": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        with right:
            st.subheader("Where a player shoots from")
            labels = {s["player_id"]: f"{s['player_name']} ({s['team_code']}, {s['attempts']} shots)" for s in shooters}
            player_id = st.selectbox("Player", list(labels), format_func=labels.get)
            with duckdb.connect(settings["db_path"], read_only=True) as db:
                shots = pd.DataFrame(queries.player_shots(db, season, player_id))
            st.altair_chart(shot_chart(shots, labels[player_id]))
            by_zone = shots.groupby("zone").agg(
                shots=("made", "size"),
                made=("made", "sum"),
                points=("value", lambda v: (v * shots.loc[v.index, "made"]).sum()),
            )
            by_zone = by_zone.loc[[z for z in ZONE_ORDER if z in by_zone.index]].reset_index()
            st.dataframe(
                pd.DataFrame(
                    {
                        "Zone": by_zone["zone"],
                        "Shots": by_zone["shots"],
                        "Made": by_zone["made"],
                        "Points per shot": by_zone["points"] / by_zone["shots"],
                    }
                ),
                hide_index=True,
                width="stretch",
                column_config={"Points per shot": st.column_config.NumberColumn(format="%.2f")},
            )
            st.caption(
                "Shot positions come on a coarse grid from the source, so nearby shots can sit on top of each other."
            )
