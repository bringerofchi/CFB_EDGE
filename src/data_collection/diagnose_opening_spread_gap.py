"""
diagnose_opening_spread_gap.py
Investigates why line_movement_toward_team showed 0 coverage for 2014-2020
but 1756 rows for 2021 in market_features.py output.

Checks the RAW CFBD lines JSON directly (bypassing all extraction logic)
to answer: is spreadOpen genuinely absent from CFBD's data for older
seasons, or is there a bug in how build_games_master.py extracts it?

Reports, per season:
  - Total games with ANY line data at all
  - Games where at least one provider has a non-null "spread" (closing)
  - Games where at least one provider has a non-null "spreadOpen"
  - Which specific providers appear, and whether spreadOpen coverage
    differs by provider (e.g. consensus vs a specific book)

Usage:
    python src/data_collection/diagnose_opening_spread_gap.py --seasons 2014-2021
"""

import argparse
import json
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)


def load_lines(season):
    path = os.path.join(RAW_DIR, "lines", "cfbd", f"lines_{season}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data", payload)


def diagnose_season(season):
    games = load_lines(season)
    if games is None:
        print(f"  No lines_{season}.json found.")
        return

    total_games = len(games)
    games_with_any_lines = 0
    games_with_close = 0
    games_with_open = 0
    provider_close_counts = {}
    provider_open_counts = {}
    sample_game_with_lines_no_open = None

    for g in games:
        lines = g.get("lines", [])
        if lines:
            games_with_any_lines += 1

        has_close = any(l.get("spread") is not None for l in lines)
        has_open = any(l.get("spreadOpen") is not None for l in lines)
        if has_close:
            games_with_close += 1
        if has_open:
            games_with_open += 1
        if has_close and not has_open and sample_game_with_lines_no_open is None:
            sample_game_with_lines_no_open = g

        for l in lines:
            provider = l.get("provider", "UNKNOWN")
            if l.get("spread") is not None:
                provider_close_counts[provider] = provider_close_counts.get(provider, 0) + 1
            if l.get("spreadOpen") is not None:
                provider_open_counts[provider] = provider_open_counts.get(provider, 0) + 1

    print(f"  Total games in raw file: {total_games}")
    print(f"  Games with any 'lines' array populated: {games_with_any_lines}")
    print(f"  Games with a non-null closing spread (any provider): {games_with_close}")
    print(f"  Games with a non-null OPENING spread (any provider): {games_with_open}")
    print(f"  Providers seen (closing spread counts): {provider_close_counts}")
    print(f"  Providers seen (opening spread counts): {provider_open_counts}")

    if games_with_close > 0 and games_with_open == 0:
        print(f"  ** CONFIRMED: closing spreads exist but NO opening spreads exist anywhere "
              f"in this season's raw data. This is a genuine CFBD data coverage gap for "
              f"{season}, not a bug in extraction — the field is simply not populated "
              f"by CFBD's source for this season. **")
    elif games_with_open > 0 and games_with_open < games_with_close:
        print(f"  Partial opening-spread coverage — some games have it, some don't. "
              f"Real partial gap, not necessarily a bug.")

    if sample_game_with_lines_no_open:
        print(f"\n  Sample game WITH closing spread but NO opening spread, for manual inspection:")
        print(f"  {json.dumps(sample_game_with_lines_no_open, indent=2)[:1500]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2014-2021")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    for season in seasons:
        print(f"\n=== Season {season} ===")
        diagnose_season(season)


if __name__ == "__main__":
    main()
