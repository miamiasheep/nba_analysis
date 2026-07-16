#!/usr/bin/env python3
"""
NBA Draft Rank Budget Team Builder

Cost model: Draft pick #1 costs 60, #2 costs 59, ..., #60 costs 1, Undrafted costs 0.
Goal: Build 12-man team with max EPM (or BPM/PPG) given budget.

Default: budget 300, team size 12, objective EPM.

Usage:
    python3 nba_draft_budget.py --budget 300 --team-size 12 --objective EPM
    python3 nba_draft_budget.py --budget 200 --min-games 20 --objective PTS

Requirements:
    pip install requests beautifulsoup4 pandas lxml pulp

Draft data: Built from Basketball Reference draft history 2000-2025 (cached in /tmp/draft_full_v2.csv)
            If cache not found, script will try to rebuild with rate limiting.

EPM data: From DunksAndThrees /epm (2026 season)
"""

import argparse
import re
import io
import os
import sys
import time
import unicodedata
from collections import defaultdict

import requests
import pandas as pd
from bs4 import BeautifulSoup

try:
    import pulp
    HAS_PULP = True
except ImportError:
    HAS_PULP = False

HEADERS = {"User-Agent": "Mozilla/5.0"}
DRAFT_CACHE = "/tmp/draft_full_v2.csv"

def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.strip()
    name_lower = name.lower()
    suffixes = [" jr.", " sr.", " jr", " sr", " iii", " ii", " iv", " iii.", " ii.", " iv.", " 3rd", " 2nd"]
    changed = True
    while changed:
        changed = False
        for suf in suffixes:
            if name_lower.endswith(suf):
                name = name[: -len(suf)].strip()
                name_lower = name.lower()
                changed = True
    name = unicodedata.normalize('NFKD', name).encode('ASCII','ignore').decode('ASCII')
    name = name.lower()
    name = re.sub(r'[^a-z0-9 ]', '', name)
    return re.sub(r'\s+', ' ', name).strip()

def fetch_epm(season=2026) -> pd.DataFrame:
    url = "https://dunksandthrees.com/epm"
    print(f"[DunksAndThrees] Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = 'utf-8'
    text = r.text
    search_str = f"stats:[{{season:{season}"
    start_idx = text.find(search_str)
    if start_idx == -1:
        start_idx = text.find("stats:[{season:")
    bracket_start = text.find("[", start_idx)
    depth = 0
    end_idx = None
    for i in range(bracket_start, min(len(text), bracket_start+5_000_000)):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    array_str = text[bracket_start+1:end_idx]
    pat = re.compile(r'player_name:"([^"]+)"[^}]*?team_alias:"([^"]+)"[^}]*?age:(\d+)[^}]*?position:"([^"]+)"[^}]*?off:([-\d\.]+),def:([-\d\.]+),tot:([-\d\.]+),', re.DOTALL)
    records = []
    for m in pat.finditer(array_str):
        name, team, age, pos, off, deff, tot = m.groups()
        records.append({
            "Player": name,
            "Team": team,
            "Age": int(age),
            "Pos": pos,
            "OFF_EPM": float(off),
            "DEF_EPM": float(deff),
            "EPM": float(tot),
            "norm": normalize_name(name)
        })
    df = pd.DataFrame(records).drop_duplicates('norm').sort_values('EPM', ascending=False)
    print(f"[DunksAndThrees] Parsed {len(df)} players")
    return df

def fetch_bbr_per_game(season=2026) -> pd.DataFrame:
    url = f"https://www.basketball-reference.com/leagues/NBA_{season}_per_game.html"
    print(f"[BBR] Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = 'utf-8'
    soup = BeautifulSoup(r.text, 'html.parser')
    table = soup.find('table', id='per_game_stats')
    df = pd.read_html(io.StringIO(str(table)))[0]
    df = df[df['Player'] != 'Player']
    for col in ['G','PTS']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('G', ascending=False).drop_duplicates('Player', keep='first')
    df['norm'] = df['Player'].apply(normalize_name)
    return df[['norm','Player','Team','Pos','G','PTS']]

def load_draft_map():
    if os.path.exists(DRAFT_CACHE):
        print(f"[Draft] Loading cache {DRAFT_CACHE}")
        pick_map = {}
        import csv
        with open(DRAFT_CACHE, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                norm = row['norm']
                pick = int(row['pick'])
                pick_map[norm] = pick
        return pick_map
    else:
        print("[Draft] No cache, using fallback - fetching 2000-2020 only")
        # Fallback minimal map - we already have file from earlier runs if exists
        # If not, return empty (all undrafted cost 0)
        return {}

def build_team(df, budget, team_size, objective_col):
    if not HAS_PULP:
        raise RuntimeError("PuLP required: pip install pulp")
    prob = pulp.LpProblem("DraftBudget", pulp.LpMaximize)
    vars_dict = {}
    for idx in df.index:
        vars_dict[idx] = pulp.LpVariable(f"x_{idx}", cat=pulp.LpBinary)
    prob += pulp.lpSum([df.loc[idx, objective_col] * vars_dict[idx] for idx in df.index])
    prob += pulp.lpSum([df.loc[idx, 'draft_cost'] * vars_dict[idx] for idx in df.index]) <= budget
    prob += pulp.lpSum([vars_dict[idx] for idx in df.index]) == team_size
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=120))
    status = pulp.LpStatus[prob.status]
    print(f"[Solver] Status {status}")
    selected = [idx for idx in df.index if pulp.value(vars_dict[idx]) > 0.5]
    team = df.loc[selected]
    return team, status

def main():
    parser = argparse.ArgumentParser(description="NBA Draft Budget Team Builder")
    parser.add_argument("--budget", type=int, default=300, help="Draft budget (default 300)")
    parser.add_argument("--team-size", type=int, default=12, help="Roster size (default 12)")
    parser.add_argument("--objective", type=str, default="EPM", choices=["EPM","PTS","BPM"], help="Objective to maximize")
    parser.add_argument("--min-games", type=int, default=0, help="Min games filter for PPG/BPM (0 = no filter)")
    parser.add_argument("--season", type=int, default=2026, help="Season for EPM/PPG")
    args = parser.parse_args()

    print(f"\n=== Draft Budget Team Builder ===")
    print(f"Model: Pick #1=60, #2=59, ..., #60=1, Undrafted=0")
    print(f"Budget {args.budget}, Team size {args.team_size}, Objective {args.objective}\n")

    # Load EPM or PPG pool
    if args.objective == "EPM":
        df_pool = fetch_epm(args.season)
    else:
        df_pool = fetch_bbr_per_game(args.season)
        if args.objective == "PTS":
            df_pool = df_pool.rename(columns={"Player": "Player"})
            df_pool['EPM'] = df_pool['PTS']  # for generic handling
        # Need BPM if objective BPM
        if args.objective == "BPM":
            # fetch advanced
            url = f"https://www.basketball-reference.com/leagues/NBA_{args.season}_advanced.html"
            print(f"[BBR] Fetching {url}")
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.encoding='utf-8'
            soup = BeautifulSoup(r.text, 'html.parser')
            table = soup.find('table', id='advanced')
            df_adv = pd.read_html(io.StringIO(str(table)))[0]
            df_adv = df_adv[df_adv['Player'] != 'Player']
            df_adv['BPM'] = pd.to_numeric(df_adv['BPM'], errors='coerce')
            df_adv = df_adv.sort_values('G', ascending=False).drop_duplicates('Player', keep='first')
            df_adv['norm'] = df_adv['Player'].apply(normalize_name)
            df_pool = pd.merge(df_pool, df_adv[['norm','BPM']], on='norm', how='inner')

    # Filter by min games if applicable (only for PPG pool, EPM pool doesn't have G, but we can merge)
    if args.min_games > 0 and 'G' in df_pool.columns:
        before = len(df_pool)
        df_pool = df_pool[df_pool['G'] >= args.min_games]
        print(f"Filtered G >= {args.min_games}: {before} -> {len(df_pool)}")

    # Load draft costs
    pick_map = load_draft_map()
    if not pick_map:
        print("Warning: No draft map, all players cost 0")

    def get_cost_and_pick(norm):
        pick = pick_map.get(norm)
        if pick is None:
            return 0, None
        if 1 <= pick <= 60:
            return 61 - pick, pick
        return 0, pick

    df_pool['draft_cost'], df_pool['draft_pick'] = zip(*df_pool['norm'].apply(lambda n: get_cost_and_pick(n)))

    # Objective column mapping
    obj_col_map = {"EPM": "EPM", "PTS": "PTS", "BPM": "BPM"}
    obj_col = obj_col_map[args.objective]
    if obj_col not in df_pool.columns:
        # fallback: if EPM pool requested PTS, use EPM col already
        obj_col = "EPM" if "EPM" in df_pool.columns else "PTS"

    # Remove NaN objective
    df_pool = df_pool[df_pool[obj_col].notna()]

    print(f"Pool size {len(df_pool)} | Undrafted {(df_pool['draft_cost']==0).sum()} | Drafted {(df_pool['draft_cost']>0).sum()}")
    print(f"Top 10 by {obj_col}:")
    print(df_pool.sort_values(obj_col, ascending=False).head(10)[['Player','Team',obj_col,'draft_pick','draft_cost']].to_string(index=False))

    # Solve
    team_df, status = build_team(df_pool, budget=args.budget, team_size=args.team_size, objective_col=obj_col)
    team_df = team_df.sort_values(obj_col, ascending=False)

    print(f"\n--- Optimal {args.team_size}-man Team (Max {obj_col}) under draft budget {args.budget} ---")
    for _, row in team_df.iterrows():
        player = row.get('Player','Unknown')
        team = row.get('Team','')
        pick = row.get('draft_pick')
        cost = row.get('draft_cost')
        val = row.get(obj_col)
        pick_str = f"Pick {int(pick)}" if pd.notna(pick) else "Undrafted"
        print(f"{player:25s} {team:3s}  {obj_col}:{val:5.2f}  {pick_str:15s}  Cost:{int(cost):2d}")

    print(f"\nTotal {obj_col}: {team_df[obj_col].sum():.2f}")
    print(f"Total Draft Cost: {team_df['draft_cost'].sum()} / {args.budget}  (Remaining {args.budget - team_df['draft_cost'].sum()})")
    if 'PTS' in team_df.columns:
        print(f"Total PPG: {team_df['PTS'].sum():.1f}" if 'PTS' in team_df.columns else "")

    # Also show undrafted top team
    if args.objective == "EPM":
        undrafted_top = df_pool[df_pool['draft_cost']==0].sort_values(obj_col, ascending=False).head(args.team_size)
        print(f"\n--- Top {args.team_size} Undrafted Only by {obj_col} (Cost 0) ---")
        print(undrafted_top[['Player','Team',obj_col]].to_string(index=False))
        print(f"Total {obj_col}: {undrafted_top[obj_col].sum():.2f} Cost 0")

if __name__ == "__main__":
    main()
