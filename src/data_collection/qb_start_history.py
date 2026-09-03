"""
qb_start_history.py
Phase 2, Signal 2 data — builds cumulative career-starts-entering-this-game
per QB, using the CHEAP design confirmed by investigate_qb_starts.py:
pull /games/players by year+week ONLY (no team filter) — this returns the
whole league in one call, ~120 calls total for 2014-2021 training period,
not the ~15,600 a naive per-team design would have cost.

STARTER IDENTIFICATION: the QB with the most pass attempts in a game is
treated as the starter. This is a proxy, not certain — a starter pulled
early for injury could finish with fewer attempts than a backup who plays
most of the game. Confirmed reasonably accurate against known 2021 reality
during investigation (Bryce Young, Stetson Bennett, Bo Nix, etc. all
correctly identified), but not perfect. Treat close calls (similar attempt
counts between two players) with extra caution.

FBS FILTERING: /games/players is not classification-filtered by CFBD
(same issue found earlier with /lines) — raw pulls include FCS teams.
Filtered here against the FBS team list from games_{season}.csv, same
fix pattern as line_reconciliation.py.

CHRONOLOGICAL ORDERING: uses actual game DATE, not week number — learned
the hard way in efficiency_features.py that week numbers collide between
regular season and postseason (a bowl game and a week-1 opener can both
be labeled "week 1"). Applying that fix here from the start.

TRANSFER RULE (decided in this project's Signal Definition Freeze): a
transfer QB's starts at a PREVIOUS school carry forward — tracked by
athlete ID (not team), so a player keeps their cumulative count across
a school change per spec §6, Signal 2.

LEFT-CENSORING CAVEAT (spec §3.2): 2014 is the first tracked season. A
player who started games before 2014 (e.g. a 2014 senior QB) will show
artificially low starts in their early 2014 games, since their true
pre-2014 history is invisible to this dataset. This is a known, documented
limitation, not something this script tries to detect or correct.

Usage:
    python src/data_collection/qb_start_history.py --seasons 2014-2021
"""

import argparse
import csv
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests --break-system-packages")
    sys.exit(1)

BASE_URL = "https://api.collegefootballdata.com"
RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))

MAX_WEEKS = 20  # generous upper bound; missing weeks just come back empty, not an error
call_count = 0


def get_api_key():
    key = os.environ.get("CFBD_API_KEY")
    if not key:
        print("ERROR: Set CFBD_API_KEY first (set CFBD_API_KEY=your_key_here)")
        sys.exit(1)
    return key


def api_get(endpoint, params, api_key):
    global call_count
    headers = {"Authorization": f"Bearer {api_key}", "accept": "application/json"}
    resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=30)
    call_count += 1
    if resp.status_code == 429:
        time.sleep(15)
        resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=30)
        call_count += 1
    if resp.status_code == 404:
        return []  # bye weeks / season end — expected, not an error
    resp.raise_for_status()
    return resp.json()


def load_fbs_teams_and_dates(season):
    """FBS team set (to filter out FCS contamination) and game_id -> date
    lookup (for chronological ordering, not week number)."""
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    fbs_teams = set()
    game_dates = {}
    if not os.path.exists(path):
        return fbs_teams, game_dates
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            home = row.get("homeTeam") or row.get("home_team")
            away = row.get("awayTeam") or row.get("away_team")
            gid = row.get("id") or row.get("gameId")
            date = (row.get("startDate") or row.get("start_date") or "")[:10]
            if home:
                fbs_teams.add(home)
            if away:
                fbs_teams.add(away)
            if gid and date:
                game_dates[str(gid)] = date
    return fbs_teams, game_dates


def extract_qb_attempts_per_game(week_data, fbs_teams):
    """From one week's /games/players response, extract (game_id, team,
    athlete_id, athlete_name, attempts) for every QB with recorded pass
    attempts, restricted to FBS teams."""
    records = []
    for game in week_data:
        game_id = str(game.get("id") or game.get("gameId") or "")
        for t in game.get("teams", []):
            team = t.get("team")
            if not team or team not in fbs_teams:
                continue
            for cat in t.get("categories", []):
                if cat.get("name", "").lower() != "passing":
                    continue
                for typ in cat.get("types", []):
                    if typ.get("name", "").upper() not in ("C/ATT", "ATT"):
                        continue
                    for athlete in typ.get("athletes", []):
                        stat = str(athlete.get("stat", "0"))
                        try:
                            attempts = int(stat.split("/")[-1])
                        except (ValueError, IndexError):
                            attempts = 0
                        athlete_id = athlete.get("id") or athlete.get("athleteId") or athlete.get("name")
                        records.append({
                            "game_id": game_id,
                            "team": team,
                            "athlete_id": athlete_id,
                            "athlete_name": athlete.get("name", ""),
                            "attempts": attempts,
                        })
    return records


def identify_starters(records):
    """Within each (game_id, team), the athlete with the most attempts is
    the likely starter. Returns one row per (game_id, team)."""
    by_game_team = {}
    for r in records:
        key = (r["game_id"], r["team"])
        if key not in by_game_team or r["attempts"] > by_game_team[key]["attempts"]:
            by_game_team[key] = r
    return list(by_game_team.values())


def pull_season(season, api_key):
    fbs_teams, game_dates = load_fbs_teams_and_dates(season)
    if not fbs_teams:
        print(f"  No games_{season}.csv found — skipping season {season}.")
        return []

    all_records = []
    for wk in range(1, MAX_WEEKS + 1):
        data = api_get("/games/players", {"year": season, "week": wk}, api_key)
        if data:
            all_records.extend(extract_qb_attempts_per_game(data, fbs_teams))

    starters = identify_starters(all_records)
    for s in starters:
        s["season"] = season
        s["date"] = game_dates.get(s["game_id"], "")
    return [s for s in starters if s["date"]]  # exclude anything we can't chronologically place


def build_career_starts(all_starters):
    """Cumulative starts BEFORE each game, tracked by athlete_id across
    schools (transfer starts carry forward, per Signal 2 freeze decision).
    Ordered by actual date across ALL seasons — not week, not season-by-season
    in isolation, since a player's career spans multiple seasons."""
    all_starters.sort(key=lambda r: (r["date"], r["season"]))

    career_count = {}  # athlete_id -> starts so far
    output = []
    for r in all_starters:
        aid = r["athlete_id"]
        prior_starts = career_count.get(aid, 0)
        output.append({
            **r,
            "career_starts_entering_this_game": prior_starts,
            "start_count_confidence": "left_censored_if_2014" if r["season"] == 2014 else "tracked",
        })
        career_count[aid] = prior_starts + 1
    return output


def main():
    parser = argparse.ArgumentParser(description="Build QB career-starts-entering-game data.")
    parser.add_argument("--seasons", default="2014-2021",
                         help="Training period default. Override touches test period — do so deliberately.")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    api_key = get_api_key()
    all_starters = []
    for season in seasons:
        print(f"Season {season}: pulling week-by-week (league-wide, cheap design)...")
        starters = pull_season(season, api_key)
        print(f"  {len(starters)} team-game starter records found. Running total calls: {call_count}")
        all_starters.extend(starters)

    if not all_starters:
        print("No data produced — check games_*.csv exists for these seasons.")
        return

    print(f"\nBuilding cumulative career-starts counts across all {len(seasons)} seasons "
          f"(chronological by DATE, not week, and not reset per season)...")
    final_rows = build_career_starts(all_starters)

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    out_path = os.path.join(PROCESSED_DIR, "qb_start_history.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["season", "date", "game_id", "team", "athlete_id", "athlete_name",
                      "attempts", "career_starts_entering_this_game", "start_count_confidence"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(final_rows)

    print(f"\nWrote {len(final_rows)} rows to {out_path}")
    print(f"Total API calls used: {call_count}")
    print("\nSpot-check: find a QB you know had a long career (e.g. a 4-year multi-year starter) "
          "and confirm their career_starts_entering_this_game climbs steadily across seasons, "
          "not resetting to 0 each year.")


if __name__ == "__main__":
    main()
