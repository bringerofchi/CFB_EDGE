"""
totals_reconciliation_audit.py
Data-quality audit ONLY — resolves SBRO's totals candidate (already sitting
unused in raw data, per the Totals Market Inefficiency proposal §5) against
CFBD's overUnder field, computes the real cross-source discrepancy
distribution, and proposes an outcome-blind quality-tier rule.

SCOPE DISCIPLINE, explicit per this session's caution: reconciliation
infrastructure runs across the full pulled range (2014-2025) — this is
data-plumbing, verifying source agreement, not evaluating a betting
hypothesis, exactly the same distinction that already lets
line_reconciliation.py span the full range for spreads. But the actual
TOLERANCE-TIER RECOMMENDATION is computed and reported ONLY from training
seasons (2014-2021) — this script is structurally incapable of using
2022-2025 for that specific step, mirroring finalize_signal_thresholds.py's
hard refusal to touch out-of-training data for threshold work.

Does NOT touch ATS or totals-outcome data anywhere. Does NOT evaluate
Candidate A. This is purely: can we reliably reconstruct a totals number,
and if so, what does "agreement between sources" mean for this market.

Usage:
    python totals_reconciliation_audit.py --seasons 2014-2025
"""

import argparse
import csv
import json
import os
import statistics
import sys

# Reuse the already-validated shared resolver and normalization logic
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from line_reconciliation import (
    RAW_DIR, SBRO_MIN_SEASON, SBRO_MAX_SEASON, load_sbro, normalize_cfbd,
    resolve_line, _safe_float,
)

TRAINING_SEASONS = set(range(2014, 2022))


def load_cfbd_totals(season):
    """Mirrors load_cfbd_lines() exactly, but extracts overUnder instead of
    spread — a field never previously used anywhere in this project."""
    path = os.path.join(RAW_DIR, "lines", "cfbd", f"lines_{season}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    games = payload.get("data", payload)
    by_id = {}
    for g in games:
        game_id = g.get("id") or g.get("gameId")
        lines = g.get("lines", [])
        preferred = [l for l in lines if (l.get("provider") or "").lower() in
                     ("consensus", "draftkings", "bovada")]
        pool = preferred if preferred else lines
        totals = [_safe_float(l.get("overUnder")) for l in pool if l.get("overUnder") is not None]
        totals = [t for t in totals if t is not None]
        by_id[game_id] = {
            "total": (sum(totals) / len(totals)) if totals else None,
            "home_team": g.get("homeTeam") or g.get("home_team"),
            "away_team": g.get("awayTeam") or g.get("away_team"),
            "start_date": (g.get("startDate") or g.get("start_date") or "")[:10],
        }
    return by_id


def load_cfbd_game_ids(season):
    """FBS game filter, same pattern already used throughout this project."""
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return {str(row.get("id") or row.get("gameId")) for row in csv.DictReader(f)}


def build_sbro_index(sbro_rows):
    by_team = {}
    for r in sbro_rows:
        by_team.setdefault(r["home_norm"], []).append(r)
        by_team.setdefault(r["away_norm"], []).append(r)
    return by_team


def find_sbro_match(sbro_by_team, home_norm, cfbd_date_str):
    """Same matching approach as production reconciliation: home team name
    + date within 1 day. Duplicated here rather than imported, to avoid
    touching the already-validated production spread-reconciliation file
    for this audit-only script."""
    from datetime import datetime, timedelta
    if not cfbd_date_str:
        return None
    try:
        cfbd_date = datetime.strptime(cfbd_date_str, "%Y-%m-%d")
    except ValueError:
        return None
    candidates = sbro_by_team.get(home_norm, [])
    for r in candidates:
        try:
            r_date = datetime.strptime(r["iso_date"], "%Y-%m-%d")
        except (ValueError, TypeError, KeyError):
            continue
        if abs((r_date - cfbd_date).days) <= 1:
            return r
    return None


def audit_season(season):
    fbs_ids = load_cfbd_game_ids(season)
    cfbd_totals = load_cfbd_totals(season)
    sbro_rows = load_sbro(season) if SBRO_MIN_SEASON <= season <= SBRO_MAX_SEASON else []
    sbro_by_team = build_sbro_index(sbro_rows)

    results = []
    for game_id, cfbd in cfbd_totals.items():
        if str(game_id) not in fbs_ids:
            continue
        cfbd_total = cfbd["total"]
        home_norm = normalize_cfbd(cfbd["home_team"])
        sbro_match = find_sbro_match(sbro_by_team, home_norm, cfbd["start_date"])

        sbro_total = None
        confidence = None
        if sbro_match:
            candidates_raw = (sbro_match.get("raw_home_close"), sbro_match.get("raw_away_close"))
            candidates = [c for c in candidates_raw if c is not None]
            if cfbd_total is not None and candidates:
                # LOCKED two-tier architecture: try cross-validation against
                # CFBD first (the shared resolver, same as spreads).
                sbro_total = resolve_line(candidates_raw, cfbd_total, fallback_value=None)
                if sbro_total is not None:
                    confidence = "cross_validated_vs_cfbd"
            if sbro_total is None and candidates:
                # No CFBD reference to validate against (the 2014-2016
                # coverage gap) — fall back to the documented heuristic:
                # totals are the LARGER of the two raw candidates (spreads
                # are the smaller one), same convention line_import.py's
                # original spread/total split was built on.
                sbro_total = max(candidates)
                confidence = "sbro_heuristic_only_unvalidated"

        # LOCKED tolerance tiers (empirically derived, 2014-2021 training
        # distribution): Verified <=0.5, Source Variance 0.5-1.25,
        # Source Conflict >1.25. Explicitly NOT the same numbers as the
        # spread tiers (2.0/7.0) — totals cluster tighter.
        discrepancy = (abs(cfbd_total - sbro_total)
                       if cfbd_total is not None and sbro_total is not None else None)

        if confidence == "cross_validated_vs_cfbd" and discrepancy is not None:
            if discrepancy <= 0.5:
                flag = "verified"
            elif discrepancy <= 1.25:
                flag = "source_variance"
            else:
                flag = "source_conflict"
        elif sbro_total is not None or cfbd_total is not None:
            flag = "single_source"
        else:
            flag = "missing"

        results.append({
            "season": season, "game_id": game_id,
            "cfbd_total": cfbd_total, "sbro_total": sbro_total,
            "discrepancy": discrepancy,
            "totals_confidence": confidence,
            "totals_market_quality_flag": flag,
        })
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", default="2014-2025")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    print("=" * 60)
    print("TOTALS RECONCILIATION — LOCKED two-tier architecture, LOCKED tolerance tiers")
    print("Verified <=0.5pts | Source Variance 0.5-1.25pts | Source Conflict >1.25pts")
    print("=" * 60)

    all_results = []
    for season in seasons:
        rows = audit_season(season)
        all_results.extend(rows)
        with_cfbd = sum(1 for r in rows if r["cfbd_total"] is not None)
        cross_val = sum(1 for r in rows if r["totals_confidence"] == "cross_validated_vs_cfbd")
        heuristic = sum(1 for r in rows if r["totals_confidence"] == "sbro_heuristic_only_unvalidated")
        verified = sum(1 for r in rows if r["totals_market_quality_flag"] == "verified")
        print(f"Season {season}: {len(rows)} games | CFBD total: {with_cfbd} | "
              f"cross-validated: {cross_val} | heuristic-only: {heuristic} | verified: {verified}")

    out_path = "totals_reconciliation_detail.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "game_id", "cfbd_total", "sbro_total",
                                                "discrepancy", "totals_confidence",
                                                "totals_market_quality_flag"])
        writer.writeheader()
        writer.writerows(all_results)
    print(f"\nWrote {out_path} ({len(all_results)} rows, all pulled seasons)")

    # ---- TRAINING-ONLY discrepancy distribution — hard scope limit ----
    training_discrepancies = sorted(
        r["discrepancy"] for r in all_results
        if r["season"] in TRAINING_SEASONS and r["discrepancy"] is not None
    )

    print("\n" + "=" * 60)
    print("DISCREPANCY DISTRIBUTION — TRAINING SEASONS ONLY (2014-2021)")
    print("This script does not compute or report this distribution for")
    print("2022-2025 under any argument — same discipline as")
    print("finalize_signal_thresholds.py. Distribution shown here is the")
    print("SAME data the tiers above were locked from originally.")
    print("=" * 60)

    if not training_discrepancies:
        print("No comparable games found in the training period.")
        return

    n = len(training_discrepancies)
    print(f"n = {n} training games with both a resolved SBRO and CFBD total")
    print(f"Mean: {statistics.mean(training_discrepancies):.2f}, "
          f"Median: {statistics.median(training_discrepancies):.2f}")
    for pct in (50, 60, 70, 75, 80, 90, 95):
        idx = min(int(n * pct / 100), n - 1)
        print(f"  {pct}th percentile: {training_discrepancies[idx]:.2f} points")

    print(f"\n** CAVEAT, recorded per the freeze decision: this distribution is built **")
    print(f"** predominantly from 2017+ observations, since CFBD totals coverage is **")
    print(f"** extremely sparse in 2014-2016. These are empirically derived reconciliation **")
    print(f"** tolerances for games where BOTH sources are available — not an estimate of **")
    print(f"** unobserved 2014-2016 cross-source variance. **")
    print(f"\nFor reference, the SPREAD tolerance tiers are: Verified <=2.0 | Variance 2.0-7.0 | Conflict >7.0")
    print(f"Totals tiers are deliberately different — tighter, matching this market's real behavior.")


if __name__ == "__main__":
    main()
