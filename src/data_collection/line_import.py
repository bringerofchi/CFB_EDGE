"""
line_import.py
Phase 1A.1 — Raw ingestion from Sportsbook Reviews Online (SBRO).

Per CFB Edge Lab Project Specification v1.3 §3.1:
  - SBRO is the PRIMARY closing-line source for seasons 2014-2022 only.
  - SBRO's archive does not cover 2023-2025 (verified in Phase 1A source
    validation) — do not attempt those seasons here.
  - Raw ingestion only. No transformations beyond parsing the page into
    rows; reconciliation against CFBD happens in line_reconciliation.py.

IMPORTANT — read before trusting the output:
  SBRO's page format pairs two rows per game (Visitor row, then Home row),
  linked by a "Rot" (rotation) number. Each row carries an Open and Close
  column, but the site does NOT label which of the two numbers (across the
  paired rows) is the POINT SPREAD and which is the TOTAL (over/under) —
  you have to infer it. The widely-used community convention (see e.g. the
  jackschooley/cfb-betting parsing approach) is:

      For a given game's two rows, the SMALLER of the two Open (or Close)
      values is the point spread magnitude, and the LARGER is the total.

  This heuristic is NOT guaranteed correct for every game — in rare cases
  (heavy blowouts with big spreads, or very low-total defensive games) the
  spread and total can be close enough in magnitude to misclassify. That is
  exactly why the project spec requires cross-checking against CFBD lines
  (line_reconciliation.py) rather than trusting either source blindly, and
  why §3.1's "Source conflict" flag exists. Treat this parser's spread
  output as a draft that reconciliation will validate, not ground truth.

Usage:
    python line_import.py --seasons 2014-2022
    python line_import.py --seasons 2021 --force

Requires: requests, beautifulsoup4, lxml
    pip install requests beautifulsoup4 lxml --break-system-packages
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependency: pip install requests beautifulsoup4 lxml --break-system-packages")
    sys.exit(1)

SCHEMA_VERSION = "1.3"
RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)

BASE_URL = "https://www.sportsbookreviewsonline.com/scoresoddsarchives"

# SBRO covers 2007-08 through 2022-23 only (verified). Season "2014" below
# means the 2014-15 archive page, which contains the fall-2014 season.
MIN_SEASON = 2014
MAX_SEASON = 2022


def season_to_url(season):
    """CFBD season year 2014 -> SBRO page 'ncaa-football-2014-15'."""
    end_yy = str(season + 1)[-2:]
    return f"{BASE_URL}/ncaa-football-{season}-{end_yy}"


def fetch_page(season):
    url = season_to_url(season)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def parse_rows(html):
    """
    Parse the odds table into raw row dicts. Returns a flat list of rows
    (not yet paired into games) in the exact column order the site uses:
    Date, Rot, VH, Team, 1st, 2nd, 3rd, 4th, Final, Open, Close, ML, 2H
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        raise ValueError("No table found on page — site layout may have changed.")

    rows = []
    trs = table.find_all("tr")
    header = [th.get_text(strip=True) for th in trs[0].find_all(["th", "td"])]

    for tr in trs[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def pair_games(rows, season):
    """
    Combine consecutive Visitor/Home row pairs into single game records.
    Applies the smaller-value-is-spread heuristic documented at the top
    of this file. Flags games where the heuristic is ambiguous
    (values within 3 points of each other) for manual review.
    """
    games = []
    i = 0
    while i < len(rows) - 1:
        r1, r2 = rows[i], rows[i + 1]
        if r1.get("VH") == "V" and r2.get("VH") == "H":
            visitor, home = r1, r2
            i += 2
        elif r1.get("VH") == "N" and r2.get("VH") == "N":
            # Neutral site game — order as listed, first row = "away" side
            visitor, home = r1, r2
            i += 2
        else:
            # Unpaired row (parsing edge case) — skip and advance one
            i += 1
            continue

        def to_float(v):
            if v in ("", "NL", "pk", "PK"):
                return 0.0 if v.lower() == "pk" else None
            try:
                return float(v)
            except ValueError:
                return None

        v_open, v_close = to_float(visitor.get("Open")), to_float(visitor.get("Close"))
        h_open, h_close = to_float(home.get("Open")), to_float(home.get("Close"))

        spread_ambiguous = False
        closing_spread = None
        if v_close is not None and h_close is not None:
            smaller, larger = min(v_close, h_close), max(v_close, h_close)
            closing_spread = smaller
            if larger - smaller < 3:
                spread_ambiguous = True

        opening_spread = None
        if v_open is not None and h_open is not None:
            opening_spread = min(v_open, h_open)

        games.append({
            "season": season,
            "date_raw": home.get("Date"),
            "away_team_raw": visitor.get("Team"),
            "home_team_raw": home.get("Team"),
            "away_final": visitor.get("Final"),
            "home_final": home.get("Final"),
            "away_open_raw": visitor.get("Open"),
            "away_close_raw": visitor.get("Close"),
            "home_open_raw": home.get("Open"),
            "home_close_raw": home.get("Close"),
            "closing_spread_parsed": closing_spread,
            "opening_spread_parsed": opening_spread,
            "spread_ambiguous_flag": spread_ambiguous,
            "away_ml": visitor.get("ML"),
            "home_ml": home.get("ML"),
        })
    return games


def write_csv(games, path, season):
    if not games:
        print(f"  WARNING: no games parsed for season {season}, skipping file")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta_cols = ["_source", "_retrieval_date", "_endpoint", "_schema_version"]
    retrieval_date = datetime.now(timezone.utc).isoformat()
    fieldnames = list(games[0].keys()) + meta_cols
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for g in games:
            g = dict(g)
            g["_source"] = "sportsbookreviewsonline.com"
            g["_retrieval_date"] = retrieval_date
            g["_endpoint"] = season_to_url(season)
            g["_schema_version"] = SCHEMA_VERSION
            writer.writerow(g)


def pull_season(season, force=False):
    path = os.path.join(RAW_DIR, "lines", "sbro", f"sbro_{season}.csv")
    if os.path.exists(path) and not force:
        print(f"  [cache] sbro_{season}.csv exists, skipping")
        return

    print(f"  fetching {season_to_url(season)}")
    html = fetch_page(season)
    rows = parse_rows(html)
    games = pair_games(rows, season)
    ambiguous = sum(1 for g in games if g["spread_ambiguous_flag"])
    write_csv(games, path, season)
    print(f"  wrote {path} ({len(games)} games, {ambiguous} flagged ambiguous spread/total split)")
    if games and ambiguous / len(games) > 0.15:
        print(f"  ** WARNING: {ambiguous}/{len(games)} games ambiguous (>15%). "
              f"Spot-check parsing before trusting this season's spreads. **")


def parse_season_range(s):
    if "-" in s:
        start, end = s.split("-")
        return list(range(int(start), int(end) + 1))
    return [int(x) for x in s.split(",")]


def main():
    parser = argparse.ArgumentParser(description="Pull raw SBRO closing-line data (2014-2022 only).")
    parser.add_argument("--seasons", default="2014-2022")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    seasons = parse_season_range(args.seasons)
    out_of_range = [s for s in seasons if s < MIN_SEASON or s > MAX_SEASON]
    if out_of_range:
        print(f"ERROR: SBRO does not cover season(s) {out_of_range}. "
              f"Valid range is {MIN_SEASON}-{MAX_SEASON} per spec §3.1. "
              f"2023-2025 must come from CFBD only (cfbd_pull.py).")
        sys.exit(1)

    for season in seasons:
        print(f"Season {season}:")
        try:
            pull_season(season, force=args.force)
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(2)  # be polite to the site between requests

    print("\nDone. Next: run line_reconciliation.py to merge with CFBD and set market_data_quality_flag.")


if __name__ == "__main__":
    main()
