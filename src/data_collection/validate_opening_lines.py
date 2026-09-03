"""
validate_opening_lines.py
Validates SBRO opening-spread data BEFORE it's promoted to games_master.csv
or any feature/signal script. Per the explicit decision this session: no
feature enters the model until its data quality is demonstrated, same
principle applied to closing spreads earlier in this project.

Reads data/processed/lines_reconciled_<season>.csv (produced by the
updated line_reconciliation.py, which now carries opening-line fields).

Reports, per the requested metrics:
  - Parse success rate: % of games where SOME sbro_opening_spread was resolved
  - Cross-validation rate: % resolved WITH a real CFBD reference vs. the
    unvalidated heuristic-only fallback
  - For cross-validated games (the only ones with real ground truth):
    error distribution by spread-size bucket, specifically checking whether
    error correlates with blowouts, pick'ems, and large market movement —
    the exact situations that broke the closing-spread parser originally
  - For heuristic-only games (no ground truth available): flags games where
    the open-to-close movement looks implausibly large as candidates for
    manual review, since that's the population most likely to share the
    original blowout-parsing bug

This script does NOT decide pass/fail. It reports the numbers; a human
reads them and decides whether to promote SBRO opening spread to
production, per this session's explicit instruction.

Usage:
    python src/data_collection/validate_opening_lines.py --seasons 2014-2021
"""

import argparse
import csv
import os
import statistics

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)
VALIDATION_DIR = os.path.abspath(os.path.join(PROCESSED_DIR, "..", "..", "analysis", "validation"))

# Spread-size buckets for error-distribution analysis, chosen to isolate
# the exact situations flagged as risky: pick'ems, moderate favorites,
# and the blowout range where the original closing-spread bug lived.
BUCKETS = [(0, 3, "pick_em_0_3"), (3, 7, "moderate_3_7"), (7, 15, "favorite_7_15"),
           (15, 30, "big_favorite_15_30"), (30, 999, "blowout_30_plus")]


def bucket_for(value):
    for lo, hi, name in BUCKETS:
        if lo <= value < hi:
            return name
    return "unknown"


def load_reconciled(season):
    path = os.path.join(PROCESSED_DIR, f"lines_reconciled_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def main():
    parser = argparse.ArgumentParser(description="Validate SBRO opening-line data before promotion.")
    parser.add_argument("--seasons", default="2014-2021")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    all_rows = []
    for season in seasons:
        all_rows.extend(load_reconciled(season))

    if not all_rows:
        print("No reconciled data found — run line_reconciliation.py first.")
        return

    total = len(all_rows)
    with_sbro_open = [r for r in all_rows if to_float(r.get("sbro_opening_spread")) is not None]
    cross_validated = [r for r in with_sbro_open if r.get("opening_line_confidence") == "cross_validated_vs_cfbd"]
    heuristic_only = [r for r in with_sbro_open if r.get("opening_line_confidence") == "sbro_heuristic_only_unvalidated"]

    print("=== OVERALL ===")
    print(f"Total games: {total}")
    print(f"Parse success rate (any sbro_opening_spread resolved): "
          f"{len(with_sbro_open)}/{total} ({len(with_sbro_open)/total*100:.1f}%)")
    print(f"Cross-validated against real CFBD reference: "
          f"{len(cross_validated)} ({len(cross_validated)/total*100:.1f}% of all games)")
    print(f"Heuristic-only, UNVALIDATED (no ground truth available): "
          f"{len(heuristic_only)} ({len(heuristic_only)/total*100:.1f}% of all games)")

    print(f"\n=== CROSS-VALIDATED GAMES — REAL ACCURACY METRICS ===")
    if not cross_validated:
        print("No cross-validated games found — cannot measure real accuracy at all. "
              "This would mean the validation is fundamentally limited to internal "
              "consistency checks only, not true error measurement.")
    else:
        diffs = [to_float(r["opening_spread_difference"]) for r in cross_validated
                 if to_float(r["opening_spread_difference"]) is not None]
        if diffs:
            print(f"n = {len(diffs)}")
            print(f"Mean absolute error: {statistics.mean(diffs):.2f} points")
            print(f"Median absolute error: {statistics.median(diffs):.2f} points")
            print(f"% within 1.0 point: {sum(1 for d in diffs if d <= 1.0)/len(diffs)*100:.1f}%")
            print(f"% within 2.0 points: {sum(1 for d in diffs if d <= 2.0)/len(diffs)*100:.1f}%")
            print(f"% requiring manual correction (>7.0 point error, same conflict "
                  f"threshold as closing spread): "
                  f"{sum(1 for d in diffs if d > 7.0)/len(diffs)*100:.1f}%")

            print(f"\nError by spread-size bucket (checking whether blowouts/pick'ems/large-movement "
                  f"games are disproportionately error-prone, per the original closing-spread bug pattern):")
            by_bucket = {}
            for r in cross_validated:
                d = to_float(r["opening_spread_difference"])
                cfbd_open = to_float(r.get("cfbd_opening_spread"))
                if d is None or cfbd_open is None:
                    continue
                b = bucket_for(abs(cfbd_open))
                by_bucket.setdefault(b, []).append(d)
            for lo, hi, name in BUCKETS:
                vals = by_bucket.get(name, [])
                if vals:
                    print(f"  {name}: n={len(vals)}, mean error={statistics.mean(vals):.2f}, "
                          f"max error={max(vals):.2f}")
                else:
                    print(f"  {name}: no games in this bucket")

            # Extract the worst individual cross-validated cases for manual
            # inspection — an aggregate bucket mean can hide exactly which
            # games are driving it. This is what actually lets a human
            # diagnose root cause instead of just seeing "8.75 mean error".
            outliers = sorted(
                [r for r in cross_validated if to_float(r.get("opening_spread_difference")) is not None],
                key=lambda r: to_float(r["opening_spread_difference"]),
                reverse=True
            )[:30]
            if outliers:
                outlier_path = os.path.join(VALIDATION_DIR, "opening_line_cross_validated_outliers.csv")
                os.makedirs(VALIDATION_DIR, exist_ok=True)
                with open(outlier_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=list(outliers[0].keys()))
                    writer.writeheader()
                    writer.writerows(outliers)
                print(f"\nWrote the 30 worst cross-validated errors (real ground truth, not just "
                      f"heuristic-only guesses) to {outlier_path} — these are the concrete cases "
                      f"to look at, not just the aggregate bucket numbers.")

    print(f"\n=== HEURISTIC-ONLY GAMES — NO GROUND TRUTH, FLAGGING SUSPICIOUS CASES ===")
    suspicious = []
    for r in heuristic_only:
        sbro_open = to_float(r["sbro_opening_spread"])
        sbro_close = to_float(r["sbro_closing_spread"])
        if sbro_open is not None and sbro_close is not None:
            implied_movement = abs(sbro_close - sbro_open)
            if implied_movement > 15.0:  # implausibly large for real line movement
                suspicious.append({**r, "implied_movement": implied_movement})
    print(f"{len(suspicious)} games flagged with >15 point implied movement (open vs. close) — "
          f"this is implausibly large for real market movement and is a strong candidate for "
          f"the same spread/total confusion bug, not genuine line movement.")

    if suspicious:
        out_path = os.path.join(VALIDATION_DIR, "opening_line_suspicious_cases.csv")
        os.makedirs(VALIDATION_DIR, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(suspicious[0].keys()))
            writer.writeheader()
            writer.writerows(suspicious)
        print(f"Wrote {len(suspicious)} suspicious cases to {out_path} for manual review.")

    print(f"\n=== RECOMMENDATION (informational only — not automatic) ===")
    if cross_validated and diffs:
        pct_good = sum(1 for d in diffs if d <= 2.0) / len(diffs) * 100
        if pct_good > 90 and len(cross_validated) >= 100:
            print(f"Cross-validated accuracy looks strong ({pct_good:.1f}% within 2 points, "
                  f"n={len(cross_validated)}) — but this sample is likely concentrated in "
                  f"2021 only (the one season with real CFBD opening coverage). Accuracy on "
                  f"2014-2020 heuristic-only games remains UNMEASURED, not just unmeasured-but-fine.")
        else:
            print(f"Cross-validated accuracy is NOT clearly strong enough to assume the "
                  f"heuristic-only years are reliable by extension. Recommend manual review "
                  f"of the suspicious-cases file before promoting to production.")
    else:
        print("Insufficient cross-validated data to make any accuracy claim. Do not promote "
              "SBRO opening spread to production based on this validation alone.")


if __name__ == "__main__":
    main()
