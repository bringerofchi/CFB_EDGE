"""
investigate_qb_starts.py
Phase 2 Step 3 investigation — figure out the cheapest reliable way to
identify the starting QB per game, BEFORE committing to a full 2014-2021 pull.

Tests two approaches on ONE team, ONE season, and reports:
  1. Call count for each approach
  2. Whether the data actually lets us identify a starter (most pass
     attempts in a game is the proxy — not perfect, but reasonable: a
     starter pulled early for injury could show fewer attempts than a
     backup who finishes the game, so treat this as a good-not-perfect
     signal, consistent with how the spec already treats other proxies)
  3. A sample of what a real career-starts count would look like

This does NOT commit to a full pull. It's a test, per the project's
established "test small, verify, then scale" pattern.

Usage:
    python src/data_collection/investigate_qb_starts.py --team Alabama --season 2021
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests --break-system-packages")
    sys.exit(1)

BASE_URL = "https://api.collegefootballdata.com"
call_count = 0


def get_api_key():
    key = os.environ.get("CFBD_API_KEY")
    if not key:
        print("ERROR: Set CFBD_API_KEY first.")
        print("  Windows: set CFBD_API_KEY=your_key_here")
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
    resp.raise_for_status()
    return resp.json()


def approach_a_no_week(team, season, api_key):
    """Test: does /games/players accept year+team WITHOUT a week filter
    and return the whole season in one call?"""
    print(f"\n--- Approach A: /games/players, year={season}, team={team}, NO week filter ---")
    try:
        data = api_get("/games/players", {"year": season, "team": team}, api_key)
        weeks_seen = set()
        for game in data:
            wk = game.get("week")
            if wk is not None:
                weeks_seen.add(wk)
        print(f"  SUCCESS: 1 call returned data. Distinct weeks present: {sorted(weeks_seen)}")
        print(f"  {'This covers a full season in ONE call — Approach A is viable and cheap.' if len(weeks_seen) > 5 else 'Only covers 1 week — week filter is effectively required, use Approach B instead.'}")
        return data, len(weeks_seen) > 5
    except requests.HTTPError as e:
        print(f"  FAILED: {e}")
        return None, False


def approach_b_per_week(team, season, api_key, max_weeks=15):
    """Test: pull week by week for the same team/season, count real cost."""
    print(f"\n--- Approach B: /games/players, year={season}, team={team}, per-week (weeks 1-{max_weeks}) ---")
    all_data = []
    for wk in range(1, max_weeks + 1):
        try:
            data = api_get("/games/players", {"year": season, "team": team, "week": wk}, api_key)
            if data:
                all_data.extend(data)
        except requests.HTTPError:
            pass  # bye weeks / season end will 404 or return empty, that's expected
    print(f"  {call_count} total API calls used so far in this script "
          f"(includes Approach A's 1 call). Weeks 1-{max_weeks} pulled individually.")
    return all_data


def approach_c_week_only_all_teams(season, api_key, week=5):
    """CRITICAL cost test: does /games/players accept year+week WITHOUT a
    team filter and return ALL teams playing that week in one call? If so,
    a full pull is ~15 calls/season x 12 seasons = ~180 calls total for
    EVERY team. If team filter is required, it's ~15 x 130 teams x 12
    seasons = tens of thousands of calls, which would blow the budget
    badly. This distinction matters enormously — test it directly, don't
    assume either way."""
    print(f"\n--- Approach C (the important one): /games/players, year={season}, "
          f"week={week}, NO team filter — does this return the whole league at once? ---")
    try:
        data = api_get("/games/players", {"year": season, "week": week}, api_key)
        teams_seen = set()
        for game in data:
            for t in game.get("teams", []):
                if t.get("team"):
                    teams_seen.add(t["team"])
        print(f"  SUCCESS: 1 call returned {len(teams_seen)} distinct teams for week {week}.")
        if len(teams_seen) > 20:
            print(f"  ** This is the cheap path. A full 2014-2021 pull would cost roughly "
                  f"15 weeks x 8 seasons = ~120 calls total, not tens of thousands. **")
        else:
            print(f"  Only {len(teams_seen)} teams returned — team filter may still be required "
                  f"for complete coverage, or this week had limited games. Worth re-testing on "
                  f"a week known to have a full slate.")
        return data, len(teams_seen)
    except requests.HTTPError as e:
        print(f"  FAILED: {e}")
        return None, 0



def try_identify_starters(data):
    """Best-effort: for each game, find the QB with the most pass attempts
    as the likely starter. Prints a sample so a human can eyeball plausibility."""
    print("\n--- Attempting to identify starting QBs from the data ---")
    found_any = False
    for game in data[:5]:  # just sample the first few games found
        game_id = game.get("id") or game.get("gameId")
        teams = game.get("teams", [])
        for t in teams:
            categories = t.get("categories", [])
            for cat in categories:
                if cat.get("name", "").lower() == "passing":
                    types = cat.get("types", [])
                    for typ in types:
                        if typ.get("name", "").upper() in ("ATT", "C/ATT"):
                            athletes = typ.get("athletes", [])
                            if athletes:
                                found_any = True
                                top = max(athletes, key=lambda a: _parse_att(a.get("stat", "0")))
                                print(f"  Game {game_id}: likely starter (most attempts) = {top.get('name')}")
    if not found_any:
        print("  Could not find a clear passing-attempts field in this response structure.")
        print("  RAW SAMPLE of first record for manual inspection:")
        print(json.dumps(data[0] if data else {}, indent=2)[:2000])


def _parse_att(stat_str):
    try:
        return int(str(stat_str).split("/")[-1])
    except (ValueError, IndexError):
        return 0


def main():
    parser = argparse.ArgumentParser(description="Investigate cheapest QB-starter identification approach.")
    parser.add_argument("--team", default="Alabama")
    parser.add_argument("--season", type=int, default=2021)
    args = parser.parse_args()

    api_key = get_api_key()
    print(f"Testing on team={args.team}, season={args.season}")

    # Test the most important cost question FIRST: can we skip per-team pulls entirely?
    data_c, teams_in_week = approach_c_week_only_all_teams(args.season, api_key)

    data_a, full_season_in_one_call = approach_a_no_week(args.team, args.season, api_key)

    if not full_season_in_one_call:
        data_b = approach_b_per_week(args.team, args.season, api_key)
        try_identify_starters(data_b)
    else:
        try_identify_starters(data_a)

    if data_c:
        try_identify_starters(data_c)

    print(f"\n=== SUMMARY ===")
    print(f"Total API calls used in this test: {call_count}")
    if teams_in_week > 20:
        print(f"GOOD NEWS: week-only pulls (no team filter) return the whole league at once.")
        print(f"Estimated full pull cost: ~15 weeks x 8 training seasons = ~120 calls total.")
        print(f"This is the design to use — pull by year+week only, extract every team's QB in one pass.")
    else:
        print(f"Week-only pull did NOT return the full league ({teams_in_week} teams found).")
        print(f"Per-team pulls may be required: ~15 x 130 teams x 8 seasons = ~15,600 calls —")
        print(f"THIS WOULD BLOW THE BUDGET. Do not commit to a full pull on this basis.")
        print(f"Re-test Approach C on a different week before deciding, or consider a cheaper proxy.")
    print(f"\nDid starter identification look plausible above? That's the real test — a wrong survey")
    print(f"of QB names is worse than no data at all.")


if __name__ == "__main__":
    main()
