#!/usr/bin/env python3
"""
NBA 2025-26 (2026) Stats Scraper
Downloads data from:
- Basketball Reference: per game (PPG) and advanced (BPM)
- DunksAndThrees: EPM

And prints Top 10 PPG, BPM, EPM for season 2026.

Usage:
    python3 nba_stats_2026.py
    python3 nba_stats_2026.py --season 2026 --min-games 50 --save

Requirements:
    pip install requests beautifulsoup4 pandas lxml
"""

import re
import io
import os
import sys
import argparse
import requests
import pandas as pd
from bs4 import BeautifulSoup
from typing import List, Tuple

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

BBR_BASE = "https://www.basketball-reference.com/leagues"


def fetch_bbr_table(season: int, table_type: str) -> pd.DataFrame:
    """
    Fetch Basketball Reference table.
    table_type: 'per_game' -> table id 'per_game_stats'
                'advanced' -> table id 'advanced'
    """
    url = f"{BBR_BASE}/NBA_{season}_{table_type}.html"
    print(f"[BBR] Fetching {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    # Fix encoding: Basketball Reference returns ISO-8859-1 header but content is UTF-8
    resp.encoding = "utf-8"
    # Basketball Reference sometimes puts tables in HTML, sometimes need parser
    soup = BeautifulSoup(resp.text, "html.parser")

    # Determine table id
    table_id_map = {
        "per_game": "per_game_stats",
        "advanced": "advanced",
        "totals": "totals_stats",
    }
    table_id = table_id_map.get(table_type, table_type)

    table = soup.find("table", id=table_id)
    if not table:
        # Try comment fallback (older versions hide tables in comments)
        from bs4 import Comment
        comments = soup.find_all(string=lambda t: isinstance(t, Comment))
        for c in comments:
            if table_id in c:
                s = BeautifulSoup(c, "html.parser")
                t = s.find("table", id=table_id)
                if t:
                    table = t
                    break
    if not table:
        raise RuntimeError(f"Could not find table {table_id} at {url}")

    # pandas read_html expects file-like or string wrapped in StringIO
    df = pd.read_html(io.StringIO(str(table)))[0]
    return df


def clean_bbr_per_game(df: pd.DataFrame) -> pd.DataFrame:
    """Clean per game dataframe"""
    # Remove repeated header rows
    if "Player" in df.columns:
        df = df[df["Player"] != "Player"]
    # Convert numeric columns
    for col in ["G", "MP", "PTS", "TRB", "AST"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def clean_bbr_advanced(df: pd.DataFrame) -> pd.DataFrame:
    if "Player" in df.columns:
        df = df[df["Player"] != "Player"]
    for col in ["G", "MP", "BPM", "OBPM", "DBPM", "PER", "VORP"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def scrape_dunksandthrees_epm(season: int = 2026) -> pd.DataFrame:
    """
    Scrape EPM from dunksandthrees.com/epm
    The page is SvelteKit rendered, but embeds data as JS:
      data:{date:"2026-06-13",stats:[{season:2026,player_name:"Victor Wembanyama",... tot:7.8 ...}, ...]}
    We extract the stats array using bracket counting and then regex-parse players.

    Returns DataFrame with columns: player_name, team, age, position, off_epm, def_epm, epm, etc.
    """
    url = "https://dunksandthrees.com/epm"
    print(f"[DunksAndThrees] Fetching {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    text = resp.text

    # Find start of stats array containing our season
    # Look for pattern stats:[{season:2026  (there could be multiple seasons, take the one with requested season)
    # We'll find the first occurrence that matches season
    search_str = f"stats:[{{season:{season}"
    start_idx = text.find(search_str)
    if start_idx == -1:
        # fallback: generic stats:[
        start_idx = text.find("stats:[{season:")
        if start_idx == -1:
            raise RuntimeError("Could not find stats array in dunksandthrees page")

    # Now we need to find the matching closing ] for this array
    # The array starts at stats:[  -> the '[' is at start_idx + len("stats:")
    bracket_start = text.find("[", start_idx)
    if bracket_start == -1:
        raise RuntimeError("Bracket not found")

    # Walk through string to balance brackets, but ignore brackets inside strings is overkill
    # Since array contains only objects without nested arrays, simple count works.
    depth = 0
    end_idx = None
    for i in range(bracket_start, min(len(text), bracket_start + 5_000_000)):  # 5MB max scan
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    if end_idx is None:
        raise RuntimeError("Could not balance brackets for stats array")

    array_str = text[bracket_start + 1 : end_idx]  # strip outer [ ]

    # Now parse each player object via regex.
    # The array_str is large:  [{season:2026,player_name:"...",...},{...}]
    # We'll use regex to extract fields
    # Pattern notes: keys are not quoted JS object notation.
    # We need: player_name, team_alias, age, position, off, def, tot
    # Also capture p_mp_48, p_usg, etc for filtering if needed.

    # Regex that captures in one object snippet
    # Use non-greedy up to tot
    player_pattern = re.compile(
        r'player_name:"([^"]+)"[^}]*?team_alias:"([^"]+)"[^}]*?age:(\d+)[^}]*?position:"([^"]+)"[^}]*?off:([-\d\.]+),def:([-\d\.]+),tot:([-\d\.]+),',
        re.DOTALL,
    )

    # Better pattern that tolerates ordering variation: off,def,tot appear together
    # We'll find all matches
    records = []
    for m in player_pattern.finditer(array_str):
        name, team, age, pos, off, deff, tot = m.groups()
        try:
            records.append(
                {
                    "Player": name,
                    "Team": team,
                    "Age": int(age),
                    "Pos": pos,
                    "OFF_EPM": float(off),
                    "DEF_EPM": float(deff),
                    "EPM": float(tot),
                }
            )
        except ValueError:
            continue

    # Fallback if above pattern fails due to field order: try second pattern without pos
    if not records:
        fallback_pat = re.compile(
            r'player_name:"([^"]+)".*?team_alias:"([^"]+)".*?off:([-\d\.]+),def:([-\d\.]+),tot:([-\d\.]+),'
        )
        for m in fallback_pat.finditer(array_str):
            name, team, off, deff, tot = m.groups()
            records.append(
                {
                    "Player": name,
                    "Team": team,
                    "Age": None,
                    "Pos": None,
                    "OFF_EPM": float(off),
                    "DEF_EPM": float(deff),
                    "EPM": float(tot),
                }
            )

    if not records:
        # Try to also extract n or mp data for filtering
        # Last resort: extract any tot
        raise RuntimeError(f"Parsed 0 EPM records for season {season}. Page structure may have changed.")

    df = pd.DataFrame(records)
    # Filter to season: already filtered by start search, but double-check size
    print(f"[DunksAndThrees] Parsed {len(df)} players for season {season}")
    return df.sort_values("EPM", ascending=False).reset_index(drop=True)


def get_top_ppg(season=2026, min_games=50) -> pd.DataFrame:
    df = fetch_bbr_table(season, "per_game")
    df = clean_bbr_per_game(df)
    if min_games:
        df_qual = df[df["G"] >= min_games]
    else:
        df_qual = df
    top = df_qual.sort_values("PTS", ascending=False).head(10)
    return top


def get_top_bpm(season=2026, min_games=50) -> pd.DataFrame:
    df = fetch_bbr_table(season, "advanced")
    df = clean_bbr_advanced(df)
    if min_games:
        df_qual = df[df["G"] >= min_games]
    else:
        df_qual = df
    # Exclude very low MP? For BPM, ensure MP >= 15 maybe
    top = df_qual.sort_values("BPM", ascending=False).head(10)
    return top


def get_top_epm(season=2026, min_games_filter=None) -> pd.DataFrame:
    # For EPM, we don't have G directly, so we filter by minutes if we had it.
    # For now just top 10 EPM sorted.
    # If we want to filter, we could need to merge with BBR for G, but let's keep raw.
    df = scrape_dunksandthrees_epm(season)
    return df.head(10)


def main():
    parser = argparse.ArgumentParser(description="NBA 2026 Top Stats Scraper")
    parser.add_argument("--season", type=int, default=2026, help="Season year (e.g., 2026 for 2025-26)")
    parser.add_argument("--min-games", type=int, default=50, help="Minimum games for qualification (BBR)")
    parser.add_argument("--save", action="store_true", help="Save CSVs to current directory")
    args = parser.parse_args()

    season = args.season
    min_games = args.min_games

    print(f"\n=== NBA {season} (2025-26) Stats ===")
    print(f"Qualification: >= {min_games} games for BBR lists\n")

    # PPG
    print(">>> Fetching PPG from Basketball Reference...")
    try:
        top_ppg = get_top_ppg(season, min_games)
        print(f"\n--- Top 10 PPG Players in {season} (min {min_games} G) ---")
        print(top_ppg[["Player", "Team", "Pos", "G", "MP", "PTS"]].to_string(index=False))
        if args.save:
            df_all = fetch_bbr_table(season, "per_game")
            df_all = clean_bbr_per_game(df_all)
            df_all.to_csv(f"bbr_per_game_{season}.csv", index=False)
            print(f"Saved bbr_per_game_{season}.csv")
    except Exception as e:
        print(f"Error fetching PPG: {e}", file=sys.stderr)
        top_ppg = pd.DataFrame()

    # BPM
    print("\n>>> Fetching BPM from Basketball Reference (advanced)...")
    try:
        top_bpm = get_top_bpm(season, min_games)
        print(f"\n--- Top 10 BPM Players in {season} (min {min_games} G) ---")
        cols = ["Player", "Team", "Pos", "G", "MP", "BPM", "OBPM", "DBPM"]
        available = [c for c in cols if c in top_bpm.columns]
        print(top_bpm[available].to_string(index=False))
        if args.save:
            df_adv = fetch_bbr_table(season, "advanced")
            df_adv = clean_bbr_advanced(df_adv)
            df_adv.to_csv(f"bbr_advanced_{season}.csv", index=False)
            print(f"Saved bbr_advanced_{season}.csv")
    except Exception as e:
        print(f"Error fetching BPM: {e}", file=sys.stderr)
        top_bpm = pd.DataFrame()

    # EPM
    print("\n>>> Fetching EPM from DunksAndThrees...")
    try:
        top_epm = get_top_epm(season)
        print(f"\n--- Top 10 EPM Players in {season} (DunksAndThrees) ---")
        print(top_epm[["Player", "Team", "Pos", "OFF_EPM", "DEF_EPM", "EPM"]].to_string(index=False))
        if args.save:
            full_epm = scrape_dunksandthrees_epm(season)
            full_epm.to_csv(f"dunksandthrees_epm_{season}.csv", index=False)
            print(f"Saved dunksandthrees_epm_{season}.csv")
    except Exception as e:
        print(f"Error fetching EPM: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        top_epm = pd.DataFrame()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
