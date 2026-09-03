"""
cfbd_pull.py
Phase 1A.1 — Raw ingestion from CollegeFootballData.com (CFBD).

Per CFB Edge Lab Project Specification v1.3:
  - Raw ingestion only. No transformations, no feature engineering.
  - Every output file carries metadata: source, retrieval_date, season,
    endpoint/file origin, schema_version.
  - CFBD free tier = 1,000 calls/month. This script caches aggressively
    (skips any file that already exists unless --force) and reports a
    running call count so you don't blow the budget mid-run.
  - CFBD is the sole source for lines in 2023-2025 (see spec §3.1, v1.3).
    For 2014-2022, CFBD lines are the SECONDARY source; SBRO (via
    line_import.py) is primary. This script pulls CFBD lines for the
    full 2014-2025 window regardless, since it's needed either way.

Usage:
    export CFBD_API_KEY="your_key_here"
    python cfbd_pull.py --seasons 2014-2025 --endpoints games,lines,ppa,advanced,roster,recruiting
    python cfbd_pull.py --seasons 2024 --endpoints games --force

Requires: requests
    pip install requests --break-system-packages
"""

import argparse
import json
import os
import sys
import time
import csv
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests --break-system-packages")
    sys.exit(1)

SCHEMA_VERSION = "1.3"
BASE_URL = "https://api.collegefootballdata.com"
RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)

MONTHLY_CALL_BUDGET = 1000
call_count = 0


def get_api_key():
    key = os.environ.get("CFBD_API_KEY")
    if not key:
        print("ERROR: Set the CFBD_API_KEY environment variable before running.")
        print("  Windows (Command Prompt):  set CFBD_API_KEY=your_key_here")
        print('  Mac/Linux:                 export CFBD_API_KEY="your_key_here"')
        print("  Then run this same command again in the SAME window.")
        sys.exit(1)
    return key


def api_get(endpoint, params, api_key):
    """Single CFBD GET call with call-count tracking and basic backoff."""
    global call_count
    if call_count >= MONTHLY_CALL_BUDGET:
        raise RuntimeError(
            f"Hit the configured monthly call budget ({MONTHLY_CALL_BUDGET}). "
            "Stopping to avoid exceeding your free-tier quota. "
            "Re-run later or raise MONTHLY_CALL_BUDGET if you're on a paid tier."
        )
    headers = {"Authorization": f"Bearer {api_key}", "accept": "application/json"}
    url = f"{BASE_URL}{endpoint}"
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    call_count += 1
    if resp.status_code == 429:
        print("  Rate limited, backing off 30s...")
        time.sleep(30)
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        call_count += 1
    resp.raise_for_status()
    return resp.json()


def wrap_metadata(data, endpoint, season):
    """Envelope every raw JSON pull with the required provenance fields."""
    return {
        "metadata": {
            "source": "CollegeFootballData.com API",
            "retrieval_date": datetime.now(timezone.utc).isoformat(),
            "season": season,
            "endpoint": endpoint,
            "schema_version": SCHEMA_VERSION,
        },
        "data": data,
    }


def write_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def write_csv_with_metadata(rows, path, season, endpoint):
    """Write list-of-dicts to CSV with provenance columns appended to every row."""
    if not rows:
        print(f"  WARNING: no rows returned for {endpoint} season {season}, skipping file")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta_cols = ["_source", "_retrieval_date", "_endpoint", "_schema_version"]
    retrieval_date = datetime.now(timezone.utc).isoformat()
    fieldnames = list(rows[0].keys()) + meta_cols
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            row = dict(row)
            row["_source"] = "CollegeFootballData.com API"
            row["_retrieval_date"] = retrieval_date
            row["_endpoint"] = endpoint
            row["_schema_version"] = SCHEMA_VERSION
            writer.writerow(row)


def already_pulled(path):
    return os.path.exists(path)


# ---------------------------------------------------------------------------
# Per-endpoint pull functions
# ---------------------------------------------------------------------------

def pull_games(season, api_key, force=False):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if already_pulled(path) and not force:
        print(f"  [cache] games_{season}.csv exists, skipping")
        return
    data = api_get("/games", {"year": season, "seasonType": "both", "classification": "fbs"}, api_key)
    write_csv_with_metadata(data, path, season, "/games")
    print(f"  wrote {path} ({len(data)} games)")


def pull_lines(season, api_key, force=False):
    path = os.path.join(RAW_DIR, "lines", "cfbd", f"lines_{season}.json")
    if already_pulled(path) and not force:
        print(f"  [cache] lines_{season}.json exists, skipping")
        return
    data = api_get("/lines", {"year": season, "seasonType": "both"}, api_key)
    write_json(wrap_metadata(data, "/lines", season), path)
    print(f"  wrote {path} ({len(data)} games with line data)")


def pull_ppa(season, api_key, force=False):
    path = os.path.join(RAW_DIR, "stats", "ppa", f"ppa_{season}.json")
    if already_pulled(path) and not force:
        print(f"  [cache] ppa_{season}.json exists, skipping")
        return
    data = api_get("/ppa/games", {"year": season}, api_key)
    write_json(wrap_metadata(data, "/ppa/games", season), path)
    print(f"  wrote {path} ({len(data)} records)")


def pull_advanced_stats(season, api_key, force=False):
    path = os.path.join(RAW_DIR, "stats", "advanced", f"advanced_{season}.json")
    if already_pulled(path) and not force:
        print(f"  [cache] advanced_{season}.json exists, skipping")
        return
    data = api_get("/stats/game/advanced", {"year": season}, api_key)
    write_json(wrap_metadata(data, "/stats/game/advanced", season), path)
    print(f"  wrote {path} ({len(data)} records)")


def pull_roster(season, api_key, force=False):
    path = os.path.join(RAW_DIR, "roster", f"roster_{season}.csv")
    if already_pulled(path) and not force:
        print(f"  [cache] roster_{season}.csv exists, skipping")
        return
    data = api_get("/roster", {"year": season}, api_key)
    write_csv_with_metadata(data, path, season, "/roster")
    print(f"  wrote {path} ({len(data)} players)")


def pull_recruiting(season, api_key, force=False):
    path = os.path.join(RAW_DIR, "roster", f"recruiting_{season}.csv")
    if already_pulled(path) and not force:
        print(f"  [cache] recruiting_{season}.csv exists, skipping")
        return
    data = api_get("/recruiting/teams", {"year": season}, api_key)
    write_csv_with_metadata(data, path, season, "/recruiting/teams")
    print(f"  wrote {path} ({len(data)} teams)")


def pull_coaches(season, api_key, force=False):
    """Coaches endpoint is pulled ONCE for a wide year range, not per-season —
    the `season` argument is ignored except to trigger this in the main loop;
    caching means it only actually fetches on the first call, no-ops after."""
    path = os.path.join(RAW_DIR, "coaches", "coaches.json")
    if already_pulled(path) and not force:
        print(f"  [cache] coaches.json exists, skipping")
        return
    # Wide range with a buffer year on each side, so continuity checks for the
    # very first/last tracked season can still see the adjacent year's coach.
    data = api_get("/coaches", {"minYear": 2013, "maxYear": 2026}, api_key)
    write_json(wrap_metadata(data, "/coaches", "2013-2026"), path)
    print(f"  wrote {path} ({len(data)} coach-season records)")


def pull_venues(season, api_key, force=False):
    """Venues endpoint has no year param — pulled once, cached, not
    re-fetched per season. Note: venue data (lat/long, dome status) is
    current-state, not historical — a stadium renovated or a team that
    changed venues mid-dataset would not be reflected retroactively. Treat
    as a reasonable approximation, not a guaranteed-accurate historical record."""
    path = os.path.join(RAW_DIR, "venues", "venues.json")
    if already_pulled(path) and not force:
        print(f"  [cache] venues.json exists, skipping")
        return
    data = api_get("/venues", {}, api_key)
    write_json(wrap_metadata(data, "/venues", "current"), path)
    print(f"  wrote {path} ({len(data)} venues)")


ENDPOINT_FUNCS = {
    "games": pull_games,
    "lines": pull_lines,
    "ppa": pull_ppa,
    "advanced": pull_advanced_stats,
    "roster": pull_roster,
    "recruiting": pull_recruiting,
    "coaches": pull_coaches,
    "venues": pull_venues,
}


def parse_season_range(s):
    if "-" in s:
        start, end = s.split("-")
        return list(range(int(start), int(end) + 1))
    return [int(x) for x in s.split(",")]


def main():
    parser = argparse.ArgumentParser(description="Pull raw CFBD data for the CFB Edge Lab.")
    parser.add_argument("--seasons", default="2014-2025", help="e.g. 2014-2025 or 2014,2015,2016")
    parser.add_argument("--endpoints", default="games,lines,ppa,advanced,roster,recruiting",
                         help="comma-separated subset of: games,lines,ppa,advanced,roster,recruiting")
    parser.add_argument("--force", action="store_true", help="re-pull even if cached file exists")
    args = parser.parse_args()

    api_key = get_api_key()
    seasons = parse_season_range(args.seasons)
    endpoints = args.endpoints.split(",")

    print(f"Pulling seasons {seasons[0]}-{seasons[-1]} for endpoints: {endpoints}")
    print(f"Raw data will land in: {RAW_DIR}")
    print(f"Monthly call budget configured: {MONTHLY_CALL_BUDGET}\n")

    for season in seasons:
        print(f"Season {season}:")
        for ep in endpoints:
            if ep not in ENDPOINT_FUNCS:
                print(f"  Unknown endpoint '{ep}', skipping")
                continue
            try:
                ENDPOINT_FUNCS[ep](season, api_key, force=args.force)
            except RuntimeError as e:
                print(f"  STOPPED: {e}")
                print(f"\nTotal API calls this run: {call_count}")
                sys.exit(1)
            except requests.HTTPError as e:
                print(f"  ERROR pulling {ep} for {season}: {e}")

    print(f"\nDone. Total API calls this run: {call_count}")


if __name__ == "__main__":
    main()
