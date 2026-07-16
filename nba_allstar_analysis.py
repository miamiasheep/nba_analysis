#!/usr/bin/env python3
"""
NBA All-Star vs Non All-Star EPM Analysis 2026 season

Definition: All-Star player = has at least 1 All-Star selection in career (per Wikipedia List of NBA All-Stars)
Non All-Star = never selected.

Data:
- EPM from dunksandthrees.com/epm (2026 season, 602 players)
- All-Star list from Wikipedia (467 players)

Usage:
    python3 nba_allstar_analysis.py

Outputs:
- Top 10 All-Star by EPM
- Bottom 10 All-Star by EPM
- Top 10 Non All-Star by EPM
"""

import re
import unicodedata
import requests
import pandas as pd
import io

HEADERS = {"User-Agent": "Mozilla/5.0"}

def normalize_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = re.sub(r'[\^\*]', '', name)
    name = name.replace('-', ' ').replace('-', ' ')
    name = unicodedata.normalize('NFKD', name).encode('ASCII','ignore').decode('ASCII')
    name = name.lower()
    name = re.sub(r'[^a-z0-9 ]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    for suf in [" jr", " sr", " iii", " ii", " iv"]:
        if name.endswith(suf):
            name = name[:-len(suf)].strip()
    return name

def fetch_epm(season=2026) -> pd.DataFrame:
    url = "https://dunksandthrees.com/epm"
    print(f"[DunksAndThrees] Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.encoding = 'utf-8'
    text = r.text
    start_idx = text.find(f"stats:[{{season:{season}")
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

def fetch_allstars_wiki() -> pd.DataFrame:
    url = "https://en.wikipedia.org/wiki/List_of_NBA_All-Stars"
    print(f"[Wikipedia] Fetching {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    dfs = pd.read_html(io.StringIO(r.text))
    # Table 1 is the big list (467 players)
    df = dfs[1]
    df['norm'] = df['Player'].apply(lambda x: normalize_name(str(x)))
    print(f"[Wikipedia] Found {len(df)} all-star players")
    return df

def main():
    df_epm = fetch_epm(2026)
    df_allstar = fetch_allstars_wiki()

    merged = pd.merge(df_epm, df_allstar[['norm']], on='norm', how='left', indicator=True)
    merged['is_allstar'] = merged['_merge'] == 'both'

    all_star_df = merged[merged['is_allstar']].copy()
    non_allstar_df = merged[~merged['is_allstar']].copy()

    print(f"\nEPM pool: {len(df_epm)} | All-Stars: {len(all_star_df)} | Non All-Stars: {len(non_allstar_df)}")

    top10_allstar = all_star_df.sort_values('EPM', ascending=False).head(10)
    bottom10_allstar = all_star_df.sort_values('EPM', ascending=True).head(10)
    top10_non = non_allstar_df.sort_values('EPM', ascending=False).head(10)

    print("\n=== Top 10 All-Star Players by EPM 2026 ===")
    print(top10_allstar[['Player','Team','Pos','EPM','OFF_EPM','DEF_EPM']].to_string(index=False))

    print("\n=== Bottom 10 All-Star Players by EPM 2026 ===")
    print(bottom10_allstar[['Player','Team','Pos','EPM','OFF_EPM','DEF_EPM']].to_string(index=False))

    print("\n=== Top 10 Non All-Star Players by EPM 2026 ===")
    print(top10_non[['Player','Team','Pos','EPM','OFF_EPM','DEF_EPM']].to_string(index=False))

    # Summary stats
    print("\n=== Summary ===")
    print(f"All-Star mean EPM: {all_star_df['EPM'].mean():.2f} median {all_star_df['EPM'].median():.2f}")
    print(f"Non All-Star mean EPM: {non_allstar_df['EPM'].mean():.2f} median {non_allstar_df['EPM'].median():.2f}")

    # Save
    top10_allstar.to_csv('top10_allstar_epm_2026.csv', index=False)
    bottom10_allstar.to_csv('bottom10_allstar_epm_2026.csv', index=False)
    top10_non.to_csv('top10_non_allstar_epm_2026.csv', index=False)
    print("\nSaved CSVs: top10_allstar_epm_2026.csv, bottom10_allstar_epm_2026.csv, top10_non_allstar_epm_2026.csv")

if __name__ == "__main__":
    main()
