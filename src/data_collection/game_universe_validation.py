"""
game_universe_validation.py
Phase 1A Step 2 — Game Universe Validation.

Per CFB Edge Lab Project Specification v1.5, this must run BEFORE
games_master.csv is built. Checks:
  A. Season game counts (flag unexpected drops/spikes)
  B. Duplicate games (season, date, home_team, away_team)
  C. Missing team/score fields
  D. FBS membership (no FCS contamination in the "FBS games" universe)
  E. COVID-19 2020 documentation (not "fixing" — documenting what happened)

Output: analysis/validation/game_universe_report.csv

Usage:
    python src/data_collection/game_universe_validation.py --seasons 2014-2025
"""

import argparse
import csv
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
VALIDATION_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "..", "analysis", "validation"))

# Expected ranges per spec Step 2A. 2020 is intentionally wide-open (COVID).
EXPECTED_RANGES = {
    **{y: (830, 910) for y in range(2014, 2020)},
    2020: (400, 700),   # COVID — conference-only schedules, many cancellations
    **{y: (830, 960) for y in range(2021, 2026)},
}


def load_games(season):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def check_season(season, games):
    total = len(games)
    lo, hi = EXPECTED_RANGES.get(season, (0, 10_000))
    count_flag = "OK"
    if total == 0:
        count_flag = "NO DATA — season not pulled or empty"
    elif total < lo:
        count_flag = f"LOW — {total} below expected range {lo}-{hi}"
    elif total > hi:
        count_flag = f"HIGH — {total} above expected range {lo}-{hi}"

    # B. Duplicate games — key on (date, home_team, away_team)
    seen = {}
    duplicates = 0
    for g in games:
        date = (g.get("startDate") or g.get("start_date") or "")[:10]
        home = g.get("homeTeam") or g.get("home_team") or ""
        away = g.get("awayTeam") or g.get("away_team") or ""
        key = (date, home, away)
        seen[key] = seen.get(key, 0) + 1
    duplicates = sum(c - 1 for c in seen.values() if c > 1)

    # C. Missing fields
    missing_home = sum(1 for g in games if not (g.get("homeTeam") or g.get("home_team")))
    missing_away = sum(1 for g in games if not (g.get("awayTeam") or g.get("away_team")))
    missing_score = sum(1 for g in games
                         if (g.get("homePoints") or g.get("home_points") or "") == ""
                         or (g.get("awayPoints") or g.get("away_points") or "") == "")

    # D. FBS membership — CFBD's /games?classification=fbs already restricts to
    # games where the HOME team is FBS-classified at pull time (see cfbd_pull.py).
    # This check confirms that filter actually took, by checking the classification
    # field if present; if the raw pull didn't include it, this is reported as
    # "unverified" rather than silently assumed passing.
    classification_field_present = any(
        (g.get("homeClassification") or g.get("home_classification")) for g in games
    )
    non_fbs_home = 0
    if classification_field_present:
        non_fbs_home = sum(
            1 for g in games
            if (g.get("homeClassification") or g.get("home_classification") or "").lower() not in ("fbs", "")
        )
    fbs_check = "unverified — classification field not in raw pull" if not classification_field_present \
        else ("OK" if non_fbs_home == 0 else f"FLAG — {non_fbs_home} games with non-FBS home team")

    return {
        "season": season,
        "total_games": total,
        "expected_range": f"{lo}-{hi}",
        "count_flag": count_flag,
        "duplicate_games": duplicates,
        "missing_home_team": missing_home,
        "missing_away_team": missing_away,
        "missing_score": missing_score,
        "fbs_membership_check": fbs_check,
        "covid_season_note": (
            "2020: reduced/conference-heavy schedule expected — not treated as a data error, "
            "per spec Step 2E (document, do not fix)"
        ) if season == 2020 else "",
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 1A Step 2 — game universe validation.")
    parser.add_argument("--seasons", default="2014-2025")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    os.makedirs(VALIDATION_DIR, exist_ok=True)
    out_path = os.path.join(VALIDATION_DIR, "game_universe_report.csv")

    rows = []
    print(f"{'Season':<8}{'Games':<8}{'Count Flag':<40}{'Dupes':<8}{'MissHome':<10}{'MissAway':<10}{'MissScore':<10}")
    for season in seasons:
        games = load_games(season)
        row = check_season(season, games)
        rows.append(row)
        print(f"{row['season']:<8}{row['total_games']:<8}{row['count_flag']:<40}"
              f"{row['duplicate_games']:<8}{row['missing_home_team']:<10}"
              f"{row['missing_away_team']:<10}{row['missing_score']:<10}")
        if row["duplicate_games"] > 0:
            print(f"  ** FLAG: {season} has {row['duplicate_games']} duplicate game(s) — investigate before games_master.csv **")
        if row["missing_home_team"] or row["missing_away_team"] or row["missing_score"]:
            print(f"  ** FLAG: {season} has missing required fields — investigate before games_master.csv **")
        if "FLAG" in row["fbs_membership_check"] or "NO DATA" in row["count_flag"]:
            print(f"  ** FLAG: {season} — {row['fbs_membership_check'] if 'FLAG' in row['fbs_membership_check'] else row['count_flag']} **")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {out_path}")
    print("Review all ** FLAG ** lines above before proceeding to games_master.csv (spec §12 Step 4, §13 gate).")


if __name__ == "__main__":
    main()
