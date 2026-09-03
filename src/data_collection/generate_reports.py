"""
generate_reports.py
Phase 1A Steps 6-7 — Manual review queue and coverage analysis.

Reads the per-game reconciliation output already produced by
line_reconciliation.py (data/processed/lines_reconciled_<season>.csv) and
games_<season>.csv (for conference breakdown) to produce:

  analysis/odds_review_queue.csv    — every Source Conflict / Missing game,
                                        ready for manual review
  analysis/odds_coverage_report.csv — season + conference breakdown of
                                        source coverage and quality tiers

Does not re-pull or re-match anything — this is a reporting layer only,
run after line_reconciliation.py.

Usage:
    python src/data_collection/generate_reports.py --seasons 2014-2025
"""

import argparse
import csv
import os

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))
ANALYSIS_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "..", "analysis"))


def load_reconciled(season):
    path = os.path.join(PROCESSED_DIR, f"lines_reconciled_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_conference_lookup(season):
    """Map normalized home team name -> conference, from games_<season>.csv."""
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    lookup = {}
    if not os.path.exists(path):
        return lookup
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            team = row.get("homeTeam") or row.get("home_team")
            conf = row.get("homeConference") or row.get("home_conference") or "Unknown"
            if team:
                lookup[team] = conf or "Unknown"
    return lookup


def suspected_issue(row):
    """Best-effort auto-classification to speed up manual review, per Step 6."""
    flag = row.get("market_data_quality_flag")
    diff = row.get("closing_spread_difference")
    if flag == "missing":
        return "no usable spread from either source"
    try:
        diff_val = float(diff) if diff else None
    except ValueError:
        diff_val = None
    if flag == "source_conflict" and diff_val is not None:
        if diff_val > 15:
            return "large gap — likely spread/total confusion in SBRO parsing (see known bug, spec §11)"
        return "moderate-large gap — check team mapping and alternate lines"
    return ""


def build_review_queue(seasons):
    rows_out = []
    for season in seasons:
        for row in load_reconciled(season):
            if row.get("market_data_quality_flag") not in ("source_conflict", "missing"):
                continue
            rows_out.append({
                "game": f"{row.get('away_team', '')} @ {row.get('home_team', '')}",
                "season": season,
                "source_1_line_cfbd": row.get("cfbd_closing_spread"),
                "source_2_line_sbro": row.get("sbro_closing_spread"),
                "difference": row.get("closing_spread_difference"),
                "suspected_issue": suspected_issue(row),
                "resolution": "",
                "verified_line": "",
                "review_notes": "",
            })
    return rows_out


def build_coverage_report(seasons):
    rows_out = []
    for season in seasons:
        reconciled = load_reconciled(season)
        conf_lookup = load_conference_lookup(season)
        if not reconciled:
            continue

        def season_row(games, label):
            total = len(games)
            with_sbro = sum(1 for r in games if r.get("sbro_closing_spread"))
            with_cfbd = sum(1 for r in games if r.get("cfbd_closing_spread"))
            with_both = sum(1 for r in games if r.get("sbro_closing_spread") and r.get("cfbd_closing_spread"))
            verified = sum(1 for r in games if r.get("market_data_quality_flag") == "verified")
            variance = sum(1 for r in games if r.get("market_data_quality_flag") == "source_variance")
            conflict = sum(1 for r in games if r.get("market_data_quality_flag") == "source_conflict")
            missing = sum(1 for r in games if r.get("market_data_quality_flag") == "missing")
            return {
                "season": season,
                "breakdown": label,
                "total_fbs_games": total,
                "games_with_sbro": with_sbro,
                "games_with_cfbd": with_cfbd,
                "games_with_2plus_sources": with_both,
                "verified": verified,
                "source_variance": variance,
                "source_conflict": conflict,
                "missing": missing,
            }

        rows_out.append(season_row(reconciled, "ALL"))

        by_conf = {}
        for r in reconciled:
            conf = conf_lookup.get(r.get("home_team"), "Unknown")
            by_conf.setdefault(conf, []).append(r)
        for conf, games in sorted(by_conf.items()):
            rows_out.append(season_row(games, conf))

    return rows_out


def main():
    parser = argparse.ArgumentParser(description="Generate odds review queue and coverage report.")
    parser.add_argument("--seasons", default="2014-2025")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    os.makedirs(ANALYSIS_DIR, exist_ok=True)

    review_rows = build_review_queue(seasons)
    review_path = os.path.join(ANALYSIS_DIR, "odds_review_queue.csv")
    if review_rows:
        with open(review_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(review_rows[0].keys()))
            writer.writeheader()
            writer.writerows(review_rows)
        print(f"Wrote {len(review_rows)} rows to {review_path}")
    else:
        print("No conflict/missing rows found — review queue is empty (nothing to write).")

    coverage_rows = build_coverage_report(seasons)
    coverage_path = os.path.join(ANALYSIS_DIR, "odds_coverage_report.csv")
    if coverage_rows:
        with open(coverage_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(coverage_rows[0].keys()))
            writer.writeheader()
            writer.writerows(coverage_rows)
        print(f"Wrote {len(coverage_rows)} rows to {coverage_path}")
    else:
        print("No reconciled data found — run line_reconciliation.py first.")


if __name__ == "__main__":
    main()
