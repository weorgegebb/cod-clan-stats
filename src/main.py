import asyncio
import json
import os

import bokeh
import pandas as pd

import callofduty
from callofduty import Mode, Platform, Title

from bokeh.io import output_file, show
from bokeh.models import ColumnDataSource
from bokeh.plotting import figure
from bokeh.transform import dodge
from bokeh.palettes import brewer

ps_players = [
    "kingfishy", "Bonj-Welson", "hillmaniaa", "SimWalson", "CrazyFoolJoe",
    "omarbeancone"
]

act_players = ["bouncybanana#6363912"]

number_of_games = 150
data_path = "data/search_data.csv"


def get_creds():
    with open("creds.json", "r") as file:
        return json.load(file)


async def get_new_user_match_metadata(client, username, platform,
                                      number_of_games):

    if (platform == "ps"):
        platform_ = Platform.PlayStation
    elif (platform == "act"):
        platform_ = Platform.Activision

    responce = await client.GetPlayerMatches(platform_,
                                             username,
                                             Title.ModernWarfare,
                                             Mode.Multiplayer,
                                             limit=number_of_games)

    metadata = {}
    for match in responce:
        match_data = await match.details()

        if match_data["mode"] != "sd":
            continue

        metadata[match_data["matchId"]] = {
            "matchStart": match_data["matchStart"],
            "matchEnd": match_data["matchEnd"],
            "map": match_data["map"]["mapId"]
        }

    return metadata


def validate_matches(metadata, min_team_size):
    """
    This function is so bad lol
    """

    # Count number of team in a match
    valid_match_counter = {}
    for user in metadata:
        for game in metadata[user]:
            if game not in valid_match_counter.keys():
                valid_match_counter[game] = 1
            if game in valid_match_counter.keys():
                valid_match_counter[game] += 1

    # Generate valid game metadata
    valid_metadata = {}
    for user in metadata:
        match_metadata = {}

        for match in metadata[user]:
            if (match in valid_match_counter.keys()) and (
                    valid_match_counter[match] >= min_team_size):
                match_metadata[match] = metadata[user][match]

        valid_metadata[user] = match_metadata

    return valid_metadata


def get_played_match_ids():
    """
    Test for data
    """
    if os.path.isfile(data_path):
        data = pd.read_csv(data_path, index_col=0)
        return data["matchId"].tolist()
    else:
        return []


def reduce_match_metadata(metadata):
    played_match_ids = get_played_match_ids()
    reduced_metadata = {}

    for user in metadata:
        user_reduced_data = {}
        for match in metadata[user]:
            if int(match) not in played_match_ids:
                user_reduced_data[match] = metadata[user][match]
        reduced_metadata[user] = user_reduced_data

    return reduced_metadata


async def build_search_game_data(client, metadata):
    """
    Download new game data and add to dataframe
    """

    data = []

    for user in metadata:
        for match_id in metadata[user]:

            start_time = metadata[user][match_id]["matchStart"]
            end_time = metadata[user][match_id]["matchEnd"]

            data_entry = {
                "user": user,
                "matchId": match_id,
                "startTime": start_time,
                "endTime": end_time,
                "map": metadata[user][match_id]["map"]
            }

            if user in ps_players:
                platform_ = Platform.PlayStation
            elif user in act_players:
                platform_ = Platform.Activision

            match_summary = await client.GetPlayerMatchesSummary(
                platform_,
                user,
                Title.ModernWarfare,
                Mode.Multiplayer,
                startTimestamp=start_time,
                endTimestamp=end_time + 1)

            data_entry.update(match_summary['sd'])
            data.append(data_entry)

    df = pd.DataFrame(data)

    return df


def update_data(df):
    if not os.path.isfile(data_path):
        df.to_csv(data_path)
        return df
    else:
        old_df = pd.read_csv(data_path, index_col=0)
        new_df = df.append(old_df, ignore_index=True)
        new_df.to_csv(data_path)
        return new_df


async def get_data():
    # Auth
    creds = get_creds()
    client = await callofduty.Login(creds["user"], creds["password"])

    # Get previous search match IDs with start and end times
    player_match_metadata = {}
    for player in ps_players:
        player_match_metadata[player] = await get_new_user_match_metadata(
            client, player, "ps", number_of_games)
    for player in act_players:
        player_match_metadata[player] = await get_new_user_match_metadata(
            client, player, "act", number_of_games)

    # Find valid squad games
    valid_player_match_metadata = validate_matches(player_match_metadata, 3)

    # Drop games already processed
    # TODO - drop known games, if data already exits
    reduced_match_metadata = reduce_match_metadata(valid_player_match_metadata)

    # Get data for new games
    new_df = await build_search_game_data(client, reduced_match_metadata)

    # Add to existing data
    updated_data = update_data(new_df)

    return updated_data


def plot_map_kds(data):
    tools = "hover, save, reset"
    TOOLTIPS = [
        ("map", "@maps"),
        ("player", "@top"),
        ("kd", "@data")
    ]
    output_file("docs/index.html")

    mapss = data["map"].unique().tolist()
    maps = [m.split("_")[1] for m in mapss]
    plot_data = {"maps": maps}

    players = data["user"].unique().tolist()
    max_kd = 0

    for player in players:
        plot_data[player] = []
        for map_ in mapss:
            player_data = data[data["user"] == player]
            player_map_data = player_data[player_data["map"] == map_]

            if not player_map_data.empty:
                total_kills = player_map_data["kills"].sum()
                total_deaths = player_map_data["deaths"].sum()
                kd = total_kills / total_deaths
                if kd > max_kd:
                    max_kd = kd
            else:
                kd = 0
            plot_data[player].append(kd)

    source = ColumnDataSource(data=plot_data)

    p = figure(x_range=maps,
               plot_height=350,
               plot_width=1000,
               title="K/D per player by map",
               toolbar_location="left",
               tools=tools,
               tooltips=TOOLTIPS)

    for i, player in enumerate(players):
        p.vbar(x=dodge("maps", -0.3 + (0.1 * i), range=p.x_range),
               top=player,
               width=0.1,
               source=source,
               color=brewer['Spectral'][len(players)][i],
               legend_label=player)

    p.y_range.start = 0
    p.y_range.end = max_kd + 0.5
    p.x_range.range_padding = 0
    p.xgrid.grid_line_color = None
    p.legend.location = "top_right"
    p.legend.orientation = "horizontal"

    show(p)


def plot_map_wl(data):
    pass


def plot_data(data):
    plot_map_kds(data)
    plot_map_wl(data)


async def main():
    data = await get_data()
    # data = pd.read_csv(data_path, index_col=0)

    # Plots
    plot_data(data)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())