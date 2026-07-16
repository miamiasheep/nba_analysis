#!/usr/bin/env python3
"""
NBA Team Budget Optimizer
Build the best 12-man team by PPG (or BPM/EPM) under a salary cap.

Data Sources:
- Basketball Reference: per_game (PPG) and advanced (BPM) for season 2026 (2025-26)
- ESPN Salaries: https://www.espn.com/nba/salaries/_/year/2026 (475 players) for 2025-26 salaries
- DunksAndThrees: EPM (optional, for EPM objective)

This solves a 0-1 knapsack with cardinality constraint using PuLP (CBC solver).

Example:
    python3 nba_team_budget.py --budget 100000000 --team-size 12 --min-games 50
    python3 nba_team_budget.py --budget 150000000 --objective bpm
    python3 nba_team_budget.py --budget 100000000 --objective epm

Requirements:
    pip install requests beautifulsoup4 pandas lxml pulp
"""

import argparse
import re
import io
import time
import unicodedata
import sys

import requests
import pandas as pd
from bs4 import BeautifulSoup

try:
    import pulp
    HAS_PULP = True
except ImportError:
    HAS_PULP = False

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = unicodedata.normalize('NFKD', name.strip()).encode('ASCII','ignore').decode('ASCII')
    name = name.lower()
    name = re.sub(r'[^a-z0-9 ]', '', name)
    return re.sub(r'\s+', ' ', name).strip()

def fetch_bbr_per_game(season=2026) -> pd.DataFrame:
    url = f"https://www.basketball-reference.com/leagues/NBA_{season}_per_game.html"
    print(f"[BBR] Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = 'utf-8'
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    table = soup.find('table', id='per_game_stats')
    if not table:
        raise RuntimeError("per_game_stats table not found")
    df = pd.read_html(io.StringIO(str(table)))[0]
    # Dedup: keep max G per player (handles 2TM)
    df = df[df['Player'] != 'Player']
    for col in ['G','PTS','MP']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('G', ascending=False).drop_duplicates('Player', keep='first')
    df['norm'] = df['Player'].apply(normalize_name)
    return df

def fetch_bbr_advanced(season=2026) -> pd.DataFrame:
    url = f"https://www.basketball-reference.com/leagues/NBA_{season}_advanced.html"
    print(f"[BBR] Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = 'utf-8'
    soup = BeautifulSoup(r.text, 'html.parser')
    table = soup.find('table', id='advanced')
    df = pd.read_html(io.StringIO(str(table)))[0]
    df = df[df['Player'] != 'Player']
    for col in ['G','BPM','OBPM','DBPM']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('G', ascending=False).drop_duplicates('Player', keep='first')
    df['norm'] = df['Player'].apply(normalize_name)
    return df[['norm','BPM','OBPM','DBPM']]

def fetch_espn_salaries(year=2026, max_pages=20) -> pd.DataFrame:
    print(f"[ESPN] Fetching salaries for year {year}")
    all_rows = []
    for page in range(1, max_pages+1):
        url = f"https://www.espn.com/nba/salaries/_/year/{year}/page/{page}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', class_='tablehead')
        if not table:
            break
        df_page = pd.read_html(io.StringIO(str(table)))[0]
        df_page = df_page[df_page[0] != 'RK']
        if df_page.empty:
            break
        all_rows.append(df_page)
        time.sleep(0.3)
    if not all_rows:
        raise RuntimeError("No salary data found")
    full = pd.concat(all_rows, ignore_index=True)
    full.columns = ['RK','NAME','TEAM','SALARY']
    full['PLAYER'] = full['NAME'].apply(lambda x: re.sub(r',.*$', '', str(x)).strip())
    full['SALARY_NUM'] = full['SALARY'].apply(lambda x: int(re.sub(r'[\$,]', '', str(x))) if pd.notna(x) else 0)
    full['norm'] = full['PLAYER'].apply(normalize_name)
    print(f"[ESPN] Got {len(full)} salaries")
    return full

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
        records.append({"Player": name, "norm": normalize_name(name), "EPM": float(tot), "OFF_EPM": float(off), "DEF_EPM": float(deff)})
    df = pd.DataFrame(records).drop_duplicates('norm').sort_values('EPM', ascending=False)
    print(f"[DunksAndThrees] Parsed {len(df)} EPM records")
    return df

def build_team(df_merged, budget=100_000_000, team_size=12, objective='PTS'):
    if not HAS_PULP:
        print("PuLP not installed, using greedy fallback (not optimal)")
        # Greedy by objective per salary
        df_sorted = df_merged.sort_values(objective, ascending=False)
        team = []
        salary_sum = 0
        ppg_sum = 0
        for _, row in df_sorted.iterrows():
            if len(team) >= team_size:
                break
            if salary_sum + row['SALARY_NUM'] <= budget:
                team.append(row)
                salary_sum += row['SALARY_NUM']
                ppg_sum += row[objective]
        return pd.DataFrame(team), salary_sum, ppg_sum

    prob = pulp.LpProblem("NBA_Team", pulp.LpMaximize)
    vars_dict = {}
    for idx in df_merged.index:
        vars_dict[idx] = pulp.LpVariable(f"x_{idx}", cat=pulp.LpBinary)

    prob += pulp.lpSum([df_merged.loc[idx, objective] * vars_dict[idx] for idx in df_merged.index])
    prob += pulp.lpSum([df_merged.loc[idx, 'SALARY_NUM'] * vars_dict[idx] for idx in df_merged.index]) <= budget
    prob += pulp.lpSum([vars_dict[idx] for idx in df_merged.index]) == team_size

    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=120))
    status = pulp.LpStatus[prob.status]
    print(f"[Solver] Status: {status}")
    if status != 'Optimal':
        # Check cheapest possible
        cheapest_sum = df_merged.nsmallest(team_size, 'SALARY_NUM')['SALARY_NUM'].sum()
        print(f"Cheapest {team_size} players cost ${cheapest_sum:,}, budget ${budget:,}")
        if cheapest_sum > budget:
            raise RuntimeError(f"No feasible team: cheapest {team_size} cost ${cheapest_sum:,} > budget ${budget:,}")

    selected = [idx for idx in df_merged.index if pulp.value(vars_dict[idx]) > 0.5]
    team_df = df_merged.loc[selected].copy()
    return team_df, team_df['SALARY_NUM'].sum(), team_df[objective].sum()

def main():
    parser = argparse.ArgumentParser(description="NBA Budget Team Builder")
    parser.add_argument("--budget", type=int, default=100_000_000, help="Salary cap in dollars (default 100M)")
    parser.add_argument("--team-size", type=int, default=12, help="Roster size (default 12)")
    parser.add_argument("--min-games", type=int, default=50, help="Min games played to qualify (default 50)")
    parser.add_argument("--season", type=int, default=2026, help="BBR season (2026 = 2025-26)")
    parser.add_argument("--salary-year", type=int, default=2026, help="ESPN salary year (2026 = 2025-26 salaries)")
    parser.add_argument("--objective", type=str, default="PTS", choices=["PTS","BPM","EPM"], help="Maximize PTS, BPM, or EPM")
    parser.add_argument("--save", action="store_true", help="Save results to CSV")
    args = parser.parse_args()

    print(f"\n=== NBA Team Builder ===")
    print(f"Objective: max {args.objective} | Budget: ${args.budget:,} | Team size: {args.team_size} | Min G: {args.min_games}\n")

    df_ppg = fetch_bbr_per_game(args.season)
    df_ppg = df_ppg[df_ppg['G'] >= args.min_games]
    print(f"Qualified players after min games filter: {len(df_ppg)}")

    df_sal = fetch_espn_salaries(args.salary_year)

    merged = pd.merge(df_ppg, df_sal, on='norm', how='inner')
    merged = merged[(merged['SALARY_NUM'] > 0) & (merged['PTS'].notna())]
    print(f"After merging PPG + Salary: {len(merged)} players")

    if args.objective == 'BPM':
        df_adv = fetch_bbr_advanced(args.season)
        merged = pd.merge(merged, df_adv, on='norm', how='inner')
        merged = merged[merged['BPM'].notna()]
        obj_col = 'BPM'
    elif args.objective == 'EPM':
        df_epm = fetch_epm(args.season)
        merged = pd.merge(merged, df_epm, on='norm', how='inner')
        merged = merged[merged['EPM'].notna()]
        obj_col = 'EPM'
    else:
        obj_col = 'PTS'

    # Sort for display
    merged = merged.sort_values(obj_col, ascending=False)

    try:
        team_df, total_sal, total_obj = build_team(merged, budget=args.budget, team_size=args.team_size, objective=obj_col)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    team_df = team_df.sort_values(obj_col, ascending=False)

    # Display
    display_cols = ['Player_x','TEAM','Pos','G','PTS','SALARY_NUM']
    if 'BPM' in team_df.columns:
        display_cols.append('BPM')
    if 'EPM' in team_df.columns:
        display_cols.append('EPM')
    # Fix column name conflicts: BBR Player is Player_x
    if 'Player_x' not in team_df.columns:
        rename_map = {c: c for c in team_df.columns if 'Player' in c}
    print(f"\n--- Optimal {args.team_size}-man Team (Max {obj_col}) under ${args.budget:,} ---")
    # Pretty print
    for _, row in team_df.iterrows():
        player = row.get('Player_x', row.get('Player', 'Unknown'))
        team = row.get('TEAM','')
        g = row.get('G',0)
        pts = row.get('PTS',0)
        sal = row.get('SALARY_NUM',0)
        extra = ""
        if obj_col == 'BPM':
            extra = f" BPM {row.get('BPM',0):.1f}"
        elif obj_col == 'EPM':
            extra = f" EPM {row.get('EPM',0):.2f}"
        print(f"{player:25s} {team:3s}  G:{int(g):2d}  PPG:{pts:4.1f}{extra}  Salary:${sal:,}")

    print(f"\nTotal {obj_col}: {total_obj:.1f}")
    print(f"Total Salary: ${total_sal:,} / ${args.budget:,}  (Remaining ${args.budget - total_sal:,})")
    print(f"Avg PPG per player: {team_df['PTS'].sum()/len(team_df):.1f}  Total PPG: {team_df['PTS'].sum():.1f}")

    if args.save:
        team_df.to_csv(f"team_{obj_col}_budget{args.budget}_size{args.team_size}.csv", index=False)
        merged.to_csv(f"merged_pool_{args.season}.csv", index=False)
        print(f"\nSaved team and pool CSVs")

if __name__ == "__main__":
    main()
