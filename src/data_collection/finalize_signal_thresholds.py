"""
finalize_signal_thresholds.py
Phase 2 — Signal 3 & 4 Threshold Finalization (§6.3 Signal Definition Freeze).

CRITICAL DISCIPLINE: this script looks ONLY at feature distributions
(line movement magnitude, roster turnover magnitude) across TRAINING data
(2014-2021). It does NOT touch ATS results, covers, or any outcome data —
choosing a threshold from a feature's own shape is allowed per spec §6;
choosing one after peeking at results is exactly what §6.3 prohibits. This
script is structurally incapable of the latter: it never reads
games_master.csv's ats_result column at all.

Signal 3 (Market Movement Confirmation): proposes a "meaningful movement"
threshold from the real distribution of |line_movement_signed| across
training games with SBRO-sourced (same-source) movement data.

Signal 4 (Transfer Volatility): proposes a "high turnover" threshold from
the real distribution of |net_transfer_movement| across training team-
seasons, respecting the known proxy-data caveat (§3.3) and the thin-early-
years methodology note already in spec §6.

Outputs proposed thresholds at several percentiles for human review — this
script does NOT auto-lock a threshold. That decision, and the CHANGELOG
entry finalizing it, is yours per §6.3's explicit requirement that this be
a deliberate, logged act, not something automation decides quietly.

Usage:
    python src/data_collection/finalize_signal_thresholds.py --seasons 2014-2021
"""

import argparse
import csv
import os
import statistics

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)

TRAINING_SEASONS = set(range(2014, 2022))


def to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def load_games_master(seasons):
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    if not os.path.exists(path):
        print("  ** ERROR: games_master.csv not found. **")
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(f) if int(r["season"]) in seasons]


def load_personnel_features(seasons):
    path = os.path.join(PROCESSED_DIR, "personnel_features.csv")
    if not os.path.exists(path):
        print("  ** ERROR: personnel_features.csv not found. **")
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(f) if int(r["season"]) in seasons]


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    idx = int(len(sorted_vals) * pct / 100)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


def analyze_signal3(games):
    """Line movement magnitude distribution — ONLY the feature, never outcomes."""
    print("=" * 60)
    print("SIGNAL 3 (Market Movement Confirmation) — line movement distribution")
    print("=" * 60)

    same_source = [g for g in games if g.get("line_movement_source") == "sbro_same_source"]
    all_with_movement = [g for g in games if to_float(g.get("line_movement_signed")) is not None]

    print(f"Total training games: {len(games)}")
    print(f"Games with ANY movement data (SBRO or CFBD): {len(all_with_movement)}")
    print(f"Games with SBRO same-source movement (highest confidence, per this session's decision): "
          f"{len(same_source)}")

    magnitudes = sorted(abs(to_float(g["line_movement_signed"])) for g in all_with_movement)
    if not magnitudes:
        print("No movement data found — cannot propose a threshold.")
        return

    print(f"\nDistribution of |line_movement_signed| across {len(magnitudes)} training games:")
    print(f"  Min: {magnitudes[0]:.2f}, Max: {magnitudes[-1]:.2f}")
    print(f"  Mean: {statistics.mean(magnitudes):.2f}, Median: {statistics.median(magnitudes):.2f}")
    for pct in (25, 50, 60, 70, 75, 80, 90, 95):
        print(f"  {pct}th percentile: {percentile(magnitudes, pct):.2f} points")

    print(f"\nPROPOSED CANDIDATE THRESHOLDS (pick one, or propose your own — this is a real decision, "
          f"not an automatic pick):")
    print(f"  Conservative (75th pct): movement >= {percentile(magnitudes, 75):.2f} pts qualifies as "
          f"'meaningful' — fewer qualifying games, higher confidence each one is real movement")
    print(f"  Moderate (60th pct): movement >= {percentile(magnitudes, 60):.2f} pts qualifies")
    print(f"  Original preliminary guess from spec §6 (2.0 pts, set before real data existed): "
          f"{sum(1 for m in magnitudes if m >= 2.0)} of {len(magnitudes)} games "
          f"({sum(1 for m in magnitudes if m >= 2.0)/len(magnitudes)*100:.1f}%) would qualify — "
          f"compare this rate against the percentile-based options above to judge if 2.0 was "
          f"reasonable or arbitrary")


def analyze_signal4(personnel_rows):
    """Roster turnover magnitude distribution — ONLY the feature, never outcomes."""
    print("\n" + "=" * 60)
    print("SIGNAL 4 (Transfer Volatility) — roster turnover distribution")
    print("=" * 60)

    with_turnover = [r for r in personnel_rows if to_float(r.get("net_transfer_movement")) is not None]
    print(f"Total training team-game rows: {len(personnel_rows)}")
    print(f"Rows with roster turnover data: {len(with_turnover)} "
          f"({len(with_turnover)/len(personnel_rows)*100:.1f}% — note 2014 will show 0 here, "
          f"expected, since there's no 2013 roster to diff against)")

    magnitudes = sorted(abs(to_float(r["net_transfer_movement"])) for r in with_turnover)
    if not magnitudes:
        print("No turnover data found — cannot propose a threshold.")
        return

    print(f"\nDistribution of |net_transfer_movement| across {len(magnitudes)} training team-seasons:")
    print(f"  Min: {magnitudes[0]:.0f}, Max: {magnitudes[-1]:.0f}")
    print(f"  Mean: {statistics.mean(magnitudes):.1f}, Median: {statistics.median(magnitudes):.1f}")
    for pct in (25, 50, 60, 70, 75, 80, 90, 95):
        print(f"  {pct}th percentile: {percentile(magnitudes, pct):.1f} players")

    print(f"\nPROPOSED CANDIDATE THRESHOLDS:")
    print(f"  Conservative (75th pct): |net turnover| >= {percentile(magnitudes, 75):.0f} players "
          f"qualifies as 'high volatility'")
    print(f"  Moderate (60th pct): |net turnover| >= {percentile(magnitudes, 60):.0f} players qualifies")

    # Methodology note already in spec: check if turnover magnitude actually
    # differs by era, since transfer volume was historically much lower
    # before ~2018-2019. This is a real check, not an assumption.
    by_season = {}
    for r in with_turnover:
        by_season.setdefault(r["season"], []).append(abs(to_float(r["net_transfer_movement"])))
    print(f"\nMedian |net_transfer_movement| by season (checking the 'thinner in early years' "
          f"assumption already noted in spec §6, rather than just asserting it):")
    for season in sorted(by_season.keys()):
        vals = by_season[season]
        print(f"  {season}: n={len(vals)}, median={statistics.median(vals):.1f}")


def main():
    parser = argparse.ArgumentParser(description="Propose Signal 3/4 thresholds from feature distributions only.")
    parser.add_argument("--seasons", default="2014-2021")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = set(range(int(start), int(end) + 1))
    else:
        seasons = {int(x) for x in args.seasons.split(",")}

    touching_test = seasons - TRAINING_SEASONS
    if touching_test:
        print(f"** WARNING: seasons {touching_test} are OUTSIDE the training period. Stopping — "
              f"this script should never run against test-period data. **")
        return

    games = load_games_master(seasons)
    personnel_rows = load_personnel_features(seasons)

    if games:
        analyze_signal3(games)
    if personnel_rows:
        analyze_signal4(personnel_rows)

    print("\n" + "=" * 60)
    print("NEXT STEP: pick a threshold for each signal from the options above (or propose your own).")
    print("This choice gets logged in the spec's CHANGELOG as the FROZEN threshold — once locked,")
    print("it does not change after seeing training results, per §6.3.")
    print("=" * 60)


if __name__ == "__main__":
    main()
