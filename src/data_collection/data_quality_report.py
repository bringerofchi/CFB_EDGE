"""
data_quality_report.py
Phase 1A Step 5 — Data Quality Report. The final gate before features.

Reads games_master.csv (and the earlier validation artifacts) and produces
a single summary: data/processed/data_quality_report.csv

Per spec §13, this is what determines whether Phase 1A Approval Criteria
are met. This script reports the numbers; it does NOT decide pass/fail —
that judgment call belongs to a human reading the output, per the spec's
own instruction not to let automation quietly wave itself through a gate.

Usage:
    python src/data_collection/data_quality_report.py --seasons 2014-2025
"""

import argparse
import csv
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))
ANALYSIS_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "..", "analysis"))
VALIDATION_DIR = os.path.join(ANALYSIS_DIR, "validation")


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description="Phase 1A Step 5 — data quality report.")
    parser.add_argument("--seasons", default="2014-2025")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = set(range(int(start), int(end) + 1))
    else:
        seasons = {int(x) for x in args.seasons.split(",")}

    games_master = load_csv(os.path.join(PROCESSED_DIR, "games_master.csv"))
    games_master = [r for r in games_master if int(r.get("season", 0)) in seasons]
    universe = load_csv(os.path.join(VALIDATION_DIR, "game_universe_report.csv"))
    market_summary = load_csv(os.path.join(VALIDATION_DIR, "market_quality_summary.csv"))
    spot_check = load_csv(os.path.join(VALIDATION_DIR, "spot_check_sample.csv"))

    if not games_master:
        print("No games_master.csv rows found for the requested seasons — "
              "run build_games_master.py first.")
        return

    total_games = len(games_master)
    by_season = {}
    for r in games_master:
        by_season.setdefault(r["season"], 0)
        by_season[r["season"]] += 1

    total_duplicates = sum(int(r.get("duplicate_games", 0)) for r in universe)
    total_missing_fields = sum(
        int(r.get("missing_home_team", 0)) + int(r.get("missing_away_team", 0)) + int(r.get("missing_score", 0))
        for r in universe
    )

    flag_counts = {}
    for r in games_master:
        flag = r.get("market_data_quality_flag", "missing")
        flag_counts[flag] = flag_counts.get(flag, 0) + 1

    def pct(n):
        return round(n / total_games * 100, 2) if total_games else 0.0

    verified_pct = pct(flag_counts.get("verified", 0))
    variance_pct = pct(flag_counts.get("source_variance", 0))
    conflict_pct = pct(flag_counts.get("source_conflict", 0))
    single_pct = pct(flag_counts.get("single_source", 0))
    missing_pct = pct(flag_counts.get("missing", 0))

    verified_count = sum(1 for r in spot_check if r)
    checked_count = sum(1 for r in spot_check if (r.get("manually_verified_correct") or "").strip() != "")
    correct_count = sum(1 for r in spot_check
                         if (r.get("manually_verified_correct") or "").strip().lower() in ("y", "yes", "true", "1"))
    spot_check_status = (
        "NOT YET MANUALLY REVIEWED — spot_check_sample.csv exists but manually_verified_correct column is empty"
        if spot_check and checked_count == 0 else
        f"{correct_count}/{checked_count} confirmed correct" if checked_count else
        "spot_check_sample.csv not found — run build_games_master.py"
    )

    unresolved_conflicts = flag_counts.get("source_conflict", 0)

    # Missing-field severity split (v1 gate logic didn't distinguish these — a fix,
    # not a loosening: duplicates remain a hard block always, since a duplicate is
    # never legitimate. Missing fields CAN be legitimate (a real cancellation/
    # postponement correctly has no score), so a small, isolated count is downgraded
    # to a review item rather than an automatic block — but it never silently passes;
    # it still requires you to look at missing_fields_detail.csv and make the call.
    missing_field_rate = (total_missing_fields / total_games) if total_games else 0
    missing_is_isolated = total_missing_fields > 0 and total_missing_fields <= 3 and missing_field_rate < 0.001

    summary = {
        "total_games": total_games,
        "seasons_covered": ",".join(sorted(by_season.keys(), key=int)),
        "duplicate_games_flagged_upstream": total_duplicates,
        "missing_required_fields_flagged_upstream": total_missing_fields,
        "pct_verified": verified_pct,
        "pct_source_variance": variance_pct,
        "pct_source_conflict": conflict_pct,
        "pct_single_source": single_pct,
        "pct_missing": missing_pct,
        "ats_spot_check_status": spot_check_status,
        "unresolved_source_conflicts": unresolved_conflicts,
        "gate_recommendation": (
            "DO NOT PROCEED — spot check not yet manually reviewed"
            if spot_check and checked_count == 0 else
            "DO NOT PROCEED — duplicate games flagged upstream, resolve first"
            if total_duplicates > 0 else
            "DO NOT PROCEED — missing required fields flagged upstream at a rate too high "
            "to be isolated cancellations; investigate systematically (see missing_fields_detail.csv)"
            if total_missing_fields > 0 and not missing_is_isolated else
            "REVIEW — small number of missing fields found, run find_missing_field_games.py and "
            "confirm each is a legitimate cancellation/postponement (not a data bug) before proceeding; "
            "also confirm unresolved source conflicts are acceptable"
            if missing_is_isolated and unresolved_conflicts > 0 else
            "REVIEW — small number of missing fields found, run find_missing_field_games.py and "
            "confirm each is a legitimate cancellation/postponement (not a data bug) before proceeding"
            if missing_is_isolated else
            "REVIEW — unresolved source conflicts remain, confirm these are acceptable before proceeding"
            if unresolved_conflicts > 0 else
            "Meets automated checks — human judgment call per spec §13 required for final approval"
        ),
    }

    out_path = os.path.join(PROCESSED_DIR, "data_quality_report.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    print(f"Wrote {out_path}\n")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nGATE RECOMMENDATION: {summary['gate_recommendation']}")
    print("This is a recommendation, not an automatic pass/fail — the actual approval "
          "decision per spec §13 is yours to make.")


if __name__ == "__main__":
    main()
