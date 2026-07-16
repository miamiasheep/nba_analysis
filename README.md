# NBA Analysis – 2025-26 Season (Labeled 2026)

Comprehensive Python toolkit to **scrape, merge, and optimize** NBA data from Basketball Reference, DunksAndThrees (EPM), ESPN Salaries, and Wikipedia All-Star history.

Built to answer:
- Who are Top 10 PPG / BPM / EPM in 2026?
- Best 12-man team under $100M salary cap?
- Best team under draft-rank budget (Lottery #1=60 … #60=1, Undrafted=0)?
- All-Star vs Non All-Star EPM comparison and underdog teams?

All results below are from live scrapes on **July 15 2026** (end of 2025-26 season).

---

## 📁 Directory Structure

```
nba_analysis/
├── README.md
├── nba_stats_2026.py          # 1. Download BBR + DunksAndThrees + Top 10 lists
├── nba_team_budget.py         # 2. Salary cap optimizer ($100M example)
├── nba_draft_budget.py        # 3. Draft rank budget optimizer (300 and 50)
├── nba_allstar_analysis.py    # 4. All-Star vs Non All-Star EPM analysis
└── data/
    ├── bbr_per_game_2026.csv          # 734 rows, per game stats
    ├── bbr_advanced_2026.csv          # 734 rows, advanced (BPM etc)
    ├── dunksandthrees_epm_2026.csv    # 602 rows, EPM 2026-06-13 final
    ├── espn_salaries_2026.csv         # 475 rows, 2025-26 salaries from ESPN
    ├── draft_full.csv                 # 1538 unique players, draft pick 2000-2025
    ├── allstars_wikipedia.csv         # 467 all-time All-Stars (Wikipedia)
    ├── top30_non_allstar_epm.csv
    ├── top10_allstar_epm_2026.csv
    └── ...
```

---

## 🔧 Installation

```bash
pip install requests beautifulsoup4 pandas lxml pulp

# On this Meta Mac:
# /Library/Developer/CommandLineTools/usr/bin/python3 -m pip install --user pulp beautifulsoup4 pandas lxml
```

---

## 📊 Data Sources & Scraping Tricks

### 1. Basketball Reference
- `https://www.basketball-reference.com/leagues/NBA_2026_per_game.html` → PPG (table id `per_game_stats`)
- `https://www.basketball-reference.com/leagues/NBA_2026_advanced.html` → BPM (id `advanced`)
- BBR returns `ISO-8859-1` header but content is UTF-8 → force `resp.encoding='utf-8'` to fix `Dončić`, `Jokić`.
- Tables sometimes hidden in HTML comments → fall back to parsing `Comment` nodes.

### 2. DunksAndThrees EPM
- `https://dunksandthrees.com/epm` is SvelteKit rendered, no public JSON API.
- Embedded data inside `<script>`: `data:{date:"2026-06-13",stats:[{season:2026,player_name:"Victor Wembanyama",tot:7.8001,...},...]}`
- Extract via bracket-balanced scan for outer `stats:[ ... ]` array (5MB scan) + regex `player_name:"...",team_alias:"...",off:...,def:...,tot:...`

### 3. ESPN Salaries
- `https://www.espn.com/nba/salaries/_/year/2026/page/{1..12}` – 40 per page, 12 pages = 475 players.
- Parse `table.tablehead`, clean `$` and `,` → `SALARY_NUM` int.

### 4. Draft History (for draft-budget model)
- BBR draft pages `NBA_{year}.html` for 2000-2025, table id `stats`, columns Rk, Pk (pick), Player.
- Rate limited (429) → cached to `data/draft_full.csv` (1538 unique, after normalizing Jr/Sr/III).

### 5. All-Star History
- Wikipedia `List of NBA All-Stars` – 467 players with at least 1 selection.
- Player clean: remove `^`, `*`, accents via `NFKD`, replace hyphen with space, strip Jr/Sr/III/II/IV suffixes.
- Merge with EPM pool: 78 career All-Stars among 602 EPM players.

---

## 🚀 Usage

### Script 1: Top 10 Lists
```bash
python3 nba_stats_2026.py --season 2026 --min-games 50 --save
```
Outputs:
- **PPG Top 10 (≥50 G):** Luka Dončić 33.5, SGA 31.1, Ant Edwards 28.8, Jaylen Brown 28.7, Tyrese Maxey 28.3, Kawhi 27.9, Mitchell 27.9, Jokić 27.7, Booker 26.1, Brunson 26.0 (PPG leader per BBR header = Luka)
- **BPM Top 10 (≥50 G):** Jokić 14.2, SGA 11.7, Wemby 10.7, Luka 9.3, Kawhi 8.0, Cade Cunningham 6.3, Maxey 5.4, Paul Reed 5.3, Mitchell 5.1, Duren 5.0 (raw without filter top is Riley Minix 25.5 in 3 games – filtered out)
- **EPM Top 10:** Wembanyama 7.80, Jokić 7.34, Kawhi 7.30, SGA 7.02, Giannis 6.65, Luka 6.41, LaMelo 5.14, Ty Jerome 5.05, KAT 4.63, Chet 4.58 (matches page snapshot on 2026-06-13)

Saves CSVs if `--save`.

### Script 2: Salary Cap Team ($100M)
Solves 0-1 knapsack + cardinality (12 players, ≤ budget) via PuLP CBC.

```bash
python3 nba_team_budget.py --budget 100000000 --team-size 12 --min-games 50 --objective PTS
python3 nba_team_budget.py --budget 100000000 --objective BPM
python3 nba_team_budget.py --budget 100000000 --objective EPM
python3 nba_team_budget.py --budget 150000000 --objective PTS   # allows SGA
```

**$100M, 12-man, G≥50, Max PPG = 241.2 PPG, $99,694,971**
- Wemby 25.0 $13.3M, Deni Avdija 24.2 $14.3M, Keyonte George 23.6 $4.27M, Reaves 23.3 $13.9M, Banchero 22.2 $15.3M, Sharpe 20.8 $8.4M, Duren 19.5 $6.48M, Bey 17.7 $6.11M, Ryan Rollins 17.3 $4M, Pritchard 17.0 $7.23M, Jaquez Jr. 15.4 $3.86M, Westbrook 15.2 $2.29M

**$100M Max BPM = 54.9 BPM** – SGA 11.7 $38.3M + Wemby 10.7 + Paul Reed 5.3 + Duren 5.0 + Avdija 4.3 + Clingan 3.0 + Mamukelashvili 2.8 + Queta 2.8 + Gillespie 2.5 + Garza 2.4 + Dru Smith 2.2 + Cam Spencer 2.2 = 178.6 PPG

**$100M Max EPM = 41.9 EPM** – Wemby 7.80 + Chet 4.58 + Jarrett Allen 3.73 + Paul Reed 3.47 + Dyson Daniels 3.46 + Ausar Thompson 3.15 + Ajay Mitchell 3.10 + Queta 3.04 + Amen Thompson 2.99 + Clingan 2.62 + Wallace 2.03 + Champagnie 1.91 = 161.0 PPG

Greedy by PPG alone gives only 116.9 PPG (Luka+SGA+4 cheap) → optimizer gains 2x via value picks.

### Script 3: Draft Rank Budget

Cost model: `#1=60, #2=59, … #60=1, Undrafted=0`. Tests front-office drafting efficiency.

```bash
python3 nba_draft_budget.py --budget 300 --team-size 12 --objective EPM
python3 nba_draft_budget.py --budget 50 --team-size 12 --objective EPM  # underdog
```

**Budget 300, Max EPM = 57.71, Cost 293/300**
- Wemby #1 60 7.80, Jokić #41 20 7.34, Kawhi #15 46 7.30, SGA #11 50 7.02, Giannis #15 46 6.65, Ty Jerome #24 37 5.05, Butler #30 31 4.48, Paul Reed #58 3 3.47, Caruso undrafted 0 2.62, Reaves undrafted 0 2.34, Champagnie undrafted 0 1.91, VanVleet undrafted 0 1.74

Key insight: Jokic #41 costs 20 vs Luka #3 costs 58 → Jokic 2.9x more efficient.

**Budget 50, Underdog, Max EPM = 28.60, Cost 50/50**
- Jokić #41 20 7.34, Paul Reed #58 3 3.47, Isaiah Hartenstein #43 18 3.12, Alex Caruso undrafted 0 2.62, Austin Reaves undrafted 0 2.34, Julian Champagnie undrafted 0 1.91, Fred VanVleet undrafted 0 1.74, Collin Gillespie undrafted 0 1.66, Sam Hauser undrafted 0 1.22, Luka Garza #52 9 1.21, Jordan Goodwin undrafted 0 1.12, Scotty Pippen Jr. undrafted 0 0.85
- 8 undrafted + 4 late 2nd-rounders. Pure undrafted top 12 = only 16.16 EPM, so mixing late picks doubles value.

### Script 4: All-Star vs Non All-Star

Career All-Star defined via Wikipedia (467 players). In 2026 EPM pool: 78 All-Stars, 524 Non.

```bash
python3 nba_allstar_analysis.py
```

- All-Star mean EPM 1.84 vs Non All-Star -1.62
- Top 10 All-Star EPM: Wemby 7.80, Jokic 7.34, Kawhi 7.30, SGA 7.02, Giannis 6.65, Luka 6.41, LaMelo 5.14, KAT 4.63, Chet 4.58, Butler 4.48
- Bottom 10 All-Star EPM (declining vets): Larry Nance Jr. -2.88, DeAndre Jordan -2.87, Lowry -2.83, Chris Paul -2.00, Khris Middleton -1.80, Draymond -1.75, Westbrook -1.65, Drummond -1.51, Hardaway Jr. -1.40, Beal -1.08
- Top 10 Non All-Star EPM: Ty Jerome 5.05, Franz Wagner 3.74, Paul Reed 3.47, Dyson Daniels 3.46, Ausar Thompson 3.15, Hartenstein 3.12, Ajay Mitchell 3.10, Queta 3.04, Amen Thompson 2.99, Derrick White 2.86
- Top 30 Non All-Star list includes Brandon Miller 2.56, Payton Pritchard 2.55, OG Anunoby 2.51, Reaves 2.34, etc.

If All-Star = 2025-26 season only (28 players per BBR AS flag):
- Top 10 AS season: Wemby 7.80, Jokic 7.34, Kawhi 7.30, SGA 7.02, Giannis 6.65, Luka 6.41, KAT 4.63, Chet 4.58, Curry 4.44, Mitchell 3.65
- Non AS top becomes LaMelo 5.14, Ty Jerome 5.05, Butler 4.48, Tatum 4.37, Embiid 4.30

---

## 📈 Average EPM per Team – 2026

- Unweighted all roster (602 players): league mean -1.17, median -1.66, average of team means -1.15. Best OKC mean 0.17, worst BKN -1.99.
- Top-8 rotation mean (likely starters+bench): league avg 1.01. Best OKC 3.31 (SGA, Chet…), BOS 2.08, GSW 2.08, SAS 2.07 (Wemby), worst SAC -0.47.
- Minutes-weighted (MP48): league -0.40, best SAS 1.88, OKC 1.82, BOS 1.56, worst BKN -2.01, WAS -1.92.
- Team total sum: OKC +3.28 best, WAS -43.05 worst.

---

## 🧠 Methodology Notes

- **Optimization:** ILP `max Σ value_i * x_i` s.t. `Σ cost_i * x_i ≤ budget`, `Σ x_i = team_size`, `x_i ∈ {0,1}`. PuLP CBC solves ~500 vars in <0.1s. Greedy fallback if pulp missing (PPG per $).
- **Name normalization:** NFKD accent stripping + lower + hyphen→space + `[^a-z0-9 ]`→space + strip suffixes jr/sr/iii/ii/iv. Critical for matching `Butler III`→`butler`, `Dončić`→`doncic`, `Gilgeous-Alexander`→`gilgeous alexander`.
- **Edge cases:** BBR has duplicate rows for traded players (`2TM` + team-specific). Deduplicate by max G. ESPN has duplicate header rows (`RK` inside table) → filter out.

---

## 🔮 Future Ideas

- Add positional constraints (PG/SG/SF/PF/C)
- Add age/injury risk weighting
- Scrape 2025-26 salaries instead of 2026-27 (currently ESPN year 2026 = 2025-26 season)
- Use Total Points or Win Shares instead of PPG
- Front-end dashboard (Streamlit)

---

## 📜 License

MIT – Use freely for research/fantasy.

Generated: 2026-07-15 via `nba_analysis/` toolkit.
