"""
find_missing_field_games.py
Diagnostic — identifies exactly which game(s) triggered the
"missing_required_fields" count in data_quality_report.csv, instead of
just reporting a number. A count alone can't be judged; the actual game
can (e.g. "this was a real cancellation" vs. "this is a real data bug").

Usage:
    python src/data_collection/find_missing_field_games.py --seasons 2014-2025
"""

import argparse
import csv
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))


def load_games(season):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2014-2025")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    found = []
    for season in seasons:
        for g in load_games(season):
            home = g.get("homeTeam") or g.get("home_team")
            away = g.get("awayTeam") or g.get("away_team")
            home_score = g.get("homePoints") or g.get("home_points") or ""
            away_score = g.get("awayPoints") or g.get("away_points") or ""
            date = (g.get("startDate") or g.get("start_date") or "")[:10]
            game_id = g.get("id") or g.get("gameId") or ""

            missing = []
            if not home:
                missing.append("home_team")
            if not away:
                missing.append("away_team")
            if home_score == "":
                missing.append("home_score")
            if away_score == "":
                missing.append("away_score")

            if missing:
                found.append({
                    "season": season, "game_id": game_id, "date": date,
                    "home_team": home, "away_team": away,
                    "home_score": home_score, "away_score": away_score,
                    "missing_fields": ",".join(missing),
                })

    if not found:
        print("No games with missing required fields found.")
        return

    print(f"Found {len(found)} game(s) with missing fields:\n")
    for g in found:
        print(f"  Season {g['season']}, {g['date']}: {g['away_team']} @ {g['home_team']} "
              f"(game_id {g['game_id']}) — missing: {g['missing_fields']}")

    out_path = os.path.join(PROCESSED_DIR, "..", "..", "analysis", "validation", "missing_fields_detail.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(found[0].keys()))
        writer.writeheader()
        writer.writerows(found)
    print(f"\nWrote detail to {out_path}")
    print("Look up each game_id (e.g. search the teams + date) to determine whether this is "
          "a real cancellation/postponement (acceptable, document it) or a genuine data gap "
          "(needs investigation).")


if __name__ == "__main__":
    main()
