"""
signal_library.py
Phase 2 — Build and evaluate all frozen signals against TRAINING data only
(2014-2021). This is the actual payoff of everything frozen in spec v2.2:
applies each signal's exact frozen definition, computes §6.2 survival
criteria, and applies §6.1's redistribution formula to whatever survives.

HARD RULE: this script only ever touches 2014-2021. It has no code path
that reads 2022-2025 data at all — not a filter applied at runtime, but
literally no function that requests those seasons, per §4's enforcement
rule (one accidental look contaminates the test window permanently).

Headline population: training-period headline evaluation uses
`market_data_quality_flag == verified` games only, per §3.1.

Outputs TWO files:
  1. data/processed/signal_evaluation_summary.csv — one row per signal
     (6 line items: Signal1, Signal2_QB5, Signal2_QB10, Signal2_QB15,
     Signal3, Signal4), with sample size, ATS%, units, season-by-season
     stability, and §6.2 survival determination (KEEP/CUT) plus the
     reason.
  2. data/processed/signal_library.csv — one row per (verified) training
     game, with a boolean qualifying flag for each of the 6 signal line
     items. This is the per-game data needed later for §7.1's Edge Score
     scoring formula, once redistribution determines final point values.

Usage:
    python src/model/signal_library.py
    (no --seasons argument — training period is hardcoded, not
    parameterizable, specifically so this script can never accidentally
    be pointed at test data by a mistyped argument)
"""

import csv
import os
import statistics

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)

TRAINING_SEASONS = list(range(2014, 2022))  # 2014-2021, hardcoded, not a parameter

UNIT_WIN = 0.91
UNIT_LOSS = -1.00
UNIT_PUSH = 0.0

SURVIVAL_ATS_FLOOR = 52.4          # §6.2 criterion 1
SURVIVAL_SEASON_STABILITY_PCT = 50.0   # §6.2 criterion 2 (>50%, not 52.4 — deliberately different, spec v2.1)
SURVIVAL_STABLE_SEASONS_NEEDED = 6      # of 8
SURVIVAL_MIN_GAMES_PRIMARY = 200        # §6.2
SURVIVAL_MIN_GAMES_SECONDARY = 100


def to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def to_int(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def load_games_master():
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = [r for r in csv.DictReader(f) if int(r["season"]) in TRAINING_SEASONS]
    return rows


def load_efficiency():
    path = os.path.join(PROCESSED_DIR, "team_performance_snapshot.csv")
    lookup = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            pct = to_float(r.get("team_efficiency_pct"))
            if pct is not None:
                lookup[(r["season"], r["team"], r["game_id"])] = pct
    return lookup


def load_qb_starts():
    path = os.path.join(PROCESSED_DIR, "qb_start_history.csv")
    lookup = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            starts = to_int(r.get("career_starts_entering_this_game"))
            if starts is not None:
                lookup[(r["season"], r["team"], r["game_id"])] = starts
    return lookup


def load_transfer_volatility_thresholds_and_values():
    """Signal 4: season-relative threshold per spec §6, index-based, floor(n*0.75).
    One value per (season, team) — net_transfer_movement is season-level,
    constant across a team's games, so dedupe before computing the threshold
    to avoid weighting teams with more games more heavily in the percentile."""
    path = os.path.join(PROCESSED_DIR, "personnel_features.csv")
    by_season_team = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["season"]) not in TRAINING_SEASONS:
                continue
            val = to_float(r.get("net_transfer_movement"))
            if val is not None:
                by_season_team[(r["season"], r["team"])] = abs(val)

    thresholds = {}  # season -> threshold value
    by_season = {}
    for (season, team), val in by_season_team.items():
        by_season.setdefault(season, []).append(val)
    for season, vals in by_season.items():
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        idx = min(int(n * 0.75), n - 1)
        thresholds[season] = vals_sorted[idx]

    return thresholds, by_season_team


def bet_result(bet_team, home_team, away_team, favorite, underdog, ats_result):
    """Given which team we're betting, translate the game's favorite/underdog-
    perspective ats_result into a win/loss/push for THIS specific bet."""
    if ats_result in ("no_line", "no_score", None, ""):
        return None
    is_favorite_bet = (bet_team == favorite)
    is_underdog_bet = (bet_team == underdog)
    if not is_favorite_bet and not is_underdog_bet:
        return None
    if ats_result == "push":
        return "push"
    if ats_result == "favorite_cover":
        return "win" if is_favorite_bet else "loss"
    if ats_result == "underdog_cover":
        return "win" if is_underdog_bet else "loss"
    return None


def evaluate_signal(name, per_game_results):
    """per_game_results: list of (season, result) where result in win/loss/push.
    Applies §6.2 survival criteria exactly."""
    n = len(per_game_results)
    wins = sum(1 for _, r in per_game_results if r == "win")
    losses = sum(1 for _, r in per_game_results if r == "loss")
    pushes = sum(1 for _, r in per_game_results if r == "push")
    decisions = wins + losses
    ats_pct = (wins / decisions * 100) if decisions else 0
    units = wins * UNIT_WIN + losses * UNIT_LOSS + pushes * UNIT_PUSH

    by_season = {}
    for season, r in per_game_results:
        by_season.setdefault(season, {"win": 0, "loss": 0, "push": 0})
        by_season[season][r] += 1

    stable_seasons = 0
    season_detail = {}
    for season in TRAINING_SEASONS:
        s = by_season.get(season, {"win": 0, "loss": 0, "push": 0})
        s_decisions = s["win"] + s["loss"]
        s_pct = (s["win"] / s_decisions * 100) if s_decisions else None
        season_detail[season] = s_pct
        if s_pct is not None and s_pct > SURVIVAL_SEASON_STABILITY_PCT:
            stable_seasons += 1

    # §6.2 survival determination
    min_required = SURVIVAL_MIN_GAMES_PRIMARY  # all 4 signals treated as primary
    reasons = []
    if n < SURVIVAL_MIN_GAMES_SECONDARY:
        keep = False
        reasons.append(f"sample size {n} below even the secondary floor of {SURVIVAL_MIN_GAMES_SECONDARY}")
    elif n < min_required:
        keep = False
        reasons.append(f"sample size {n} below the primary floor of {min_required}")
    else:
        keep = True

    if keep and ats_pct < SURVIVAL_ATS_FLOOR:
        keep = False
        reasons.append(f"ATS% {ats_pct:.1f} below the {SURVIVAL_ATS_FLOOR}% breakeven floor")

    if keep and stable_seasons < SURVIVAL_STABLE_SEASONS_NEEDED:
        keep = False
        reasons.append(f"only {stable_seasons}/8 seasons above {SURVIVAL_SEASON_STABILITY_PCT}%, "
                        f"need {SURVIVAL_STABLE_SEASONS_NEEDED}/8")

    return {
        "signal": name,
        "n": n,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "ats_pct": round(ats_pct, 2),
        "units": round(units, 2),
        "stable_seasons_of_8": stable_seasons,
        "survives_6_2": keep,
        "reason_if_cut": "; ".join(reasons) if reasons else "PASSES all §6.2 criteria",
        "season_ats_pct_detail": {k: (round(v, 1) if v is not None else None) for k, v in season_detail.items()},
    }


def main():
    print("Loading training-period data (2014-2021 only)...")
    games = load_games_master()
    verified_games = [g for g in games if g.get("market_data_quality_flag") == "verified"]
    print(f"  {len(games)} total training games, {len(verified_games)} Verified (headline population per §3.1)")

    efficiency = load_efficiency()
    qb_starts = load_qb_starts()
    transfer_thresholds, transfer_values = load_transfer_volatility_thresholds_and_values()
    print(f"  Loaded efficiency ({len(efficiency)}), QB starts ({len(qb_starts)}), "
          f"transfer volatility ({len(transfer_values)} team-seasons)")

    signal1_results = []
    signal2_5_results, signal2_10_results, signal2_15_results = [], [], []
    signal3_results = []
    signal4_results = []

    per_game_flags = []

    for g in verified_games:
        season, game_id = g["season"], g["game_id"]
        home, away = g["home_team"], g["away_team"]
        favorite, underdog = g.get("favorite"), g.get("underdog")
        ats_result = g.get("ats_result")
        flags = {"season": season, "game_id": game_id, "home_team": home, "away_team": away}

        # SIGNAL 1: Hidden Efficiency Underdog
        s1_fire = False
        if favorite and underdog:
            udog_pct = efficiency.get((season, underdog, game_id))
            fav_pct = efficiency.get((season, favorite, game_id))
            if udog_pct is not None and fav_pct is not None and (udog_pct - fav_pct) >= 15.0:
                s1_fire = True
                r = bet_result(underdog, home, away, favorite, underdog, ats_result)
                if r:
                    signal1_results.append((int(season), r))
        flags["signal1_hidden_efficiency_underdog"] = s1_fire

        # SIGNAL 2 (x3): Experienced QB Underdog
        for thresh, bucket, key in ((5, signal2_5_results, "signal2_qb5_underdog"),
                                     (10, signal2_10_results, "signal2_qb10_underdog"),
                                     (15, signal2_15_results, "signal2_qb15_underdog")):
            fire = False
            if underdog:
                starts = qb_starts.get((season, underdog, game_id))
                if starts is not None and starts >= thresh:
                    fire = True
                    r = bet_result(underdog, home, away, favorite, underdog, ats_result)
                    if r:
                        bucket.append((int(season), r))
            flags[key] = fire

        # SIGNAL 3: Market Movement Confirmation
        s3_fire = False
        movement = to_float(g.get("line_movement_signed"))
        if movement is not None and abs(movement) >= 2.0:
            s3_fire = True
            bet_team = away if movement > 0 else home
            r = bet_result(bet_team, home, away, favorite, underdog, ats_result)
            if r:
                signal3_results.append((int(season), r))
        flags["signal3_market_movement"] = s3_fire

        # SIGNAL 4: Transfer Volatility (directional rule, spec v2.2)
        s4_fire = False
        season_thresh = transfer_thresholds.get(season)
        home_val = transfer_values.get((season, home))
        away_val = transfer_values.get((season, away))
        if season_thresh is not None and home_val is not None and away_val is not None:
            home_qualifies = home_val >= season_thresh
            away_qualifies = away_val >= season_thresh
            if home_qualifies and not away_qualifies:
                s4_fire = True
                r = bet_result(away, home, away, favorite, underdog, ats_result)  # bet the opponent
                if r:
                    signal4_results.append((int(season), r))
            elif away_qualifies and not home_qualifies:
                s4_fire = True
                r = bet_result(home, home, away, favorite, underdog, ats_result)  # bet the opponent
                if r:
                    signal4_results.append((int(season), r))
            # both or neither qualify -> no signal, per frozen directional rule
        flags["signal4_transfer_volatility"] = s4_fire

        per_game_flags.append(flags)

    # Evaluate all 6 signal line items
    summary = [
        evaluate_signal("Signal1_HiddenEfficiencyUnderdog", signal1_results),
        evaluate_signal("Signal2_QB5_ExperiencedUnderdog", signal2_5_results),
        evaluate_signal("Signal2_QB10_ExperiencedUnderdog", signal2_10_results),
        evaluate_signal("Signal2_QB15_ExperiencedUnderdog", signal2_15_results),
        evaluate_signal("Signal3_MarketMovementConfirmation", signal3_results),
        evaluate_signal("Signal4_TransferVolatility", signal4_results),
    ]

    print(f"\n{'Signal':<38}{'N':<7}{'ATS%':<8}{'Units':<9}{'Stable':<9}{'Survives §6.2'}")
    for s in summary:
        print(f"{s['signal']:<38}{s['n']:<7}{s['ats_pct']:<8}{s['units']:<9}"
              f"{s['stable_seasons_of_8']}/8      {s['survives_6_2']}")
        if not s["survives_6_2"]:
            print(f"    -> CUT: {s['reason_if_cut']}")

    # Write summary (flatten season detail into columns)
    summary_path = os.path.join(PROCESSED_DIR, "signal_evaluation_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["signal", "n", "wins", "losses", "pushes", "ats_pct", "units",
                      "stable_seasons_of_8", "survives_6_2", "reason_if_cut"] + \
                     [f"season_{s}_ats_pct" for s in TRAINING_SEASONS]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in summary:
            row = {k: v for k, v in s.items() if k != "season_ats_pct_detail"}
            for season in TRAINING_SEASONS:
                row[f"season_{season}_ats_pct"] = s["season_ats_pct_detail"].get(season)
            writer.writerow(row)
    print(f"\nWrote {summary_path}")

    # Write per-game qualifying flags
    library_path = os.path.join(PROCESSED_DIR, "signal_library.csv")
    with open(library_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(per_game_flags[0].keys()))
        writer.writeheader()
        writer.writerows(per_game_flags)
    print(f"Wrote {library_path} ({len(per_game_flags)} verified training games)")

    print("\nNext: review survives_6_2 column. Signals marked False get cut per §6.1 — "
          "their points redistribute among surviving signals in the same category using "
          "the frozen ATS-edge-proportional formula, with the equal-split fallback if any "
          "tie group sums to exactly zero edge.")


if __name__ == "__main__":
    main()
