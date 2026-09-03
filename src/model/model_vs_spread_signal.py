"""
model_vs_spread_signal.py
Evaluates the frozen Model-vs-Spread Discrepancy signal (spec §18) against
TRAINING data only (2014-2021). Mirrors signal_library.py's discipline:
hardcoded training seasons, Verified-only population, mechanical §6.2
application, permanent unedited output.

Full chain, exactly as frozen in §18:
  1. model_spread_home = (homePregameElo - awayPregameElo) / 25
  2. No researcher-added HFA adjustment
  3. market_spread_home = same sign convention (positive = home favored)
  4. discrepancy = model_spread_home - market_spread_home
  5. Directional rule: positive -> bet home; negative -> bet away
  6. T = 75th percentile of |discrepancy| across the construction
     population (single fixed rule, no candidates)
  7. Validity gate: T == 0 exactly -> signal invalid, fires for no game
  8. Two independent 200-game floors: construction population AND
     triggered sample must each independently clear 200
  9. Elo qualification: exclusion, not imputation
  10. Pregame Elo only, never postgame
  11. No new data pull required

Usage:
    python src/model/model_vs_spread_signal.py
    (no arguments - training period hardcoded, same safety design as
    signal_library.py and signal_library_2a.py)
"""

import csv
import os

PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
PROCESSED_DIR = os.path.abspath(PROCESSED_DIR)
RAW_DIR = os.path.abspath(os.path.join(PROCESSED_DIR, "..", "raw"))

TRAINING_SEASONS = list(range(2014, 2022))  # hardcoded, not a parameter

UNIT_WIN = 0.91
UNIT_LOSS = -1.00
UNIT_PUSH = 0.0

SURVIVAL_ATS_FLOOR = 52.4
SURVIVAL_SEASON_STABILITY_PCT = 50.0
SURVIVAL_STABLE_SEASONS_NEEDED = 6
CONSTRUCTION_POPULATION_FLOOR = 200
TRIGGERED_SAMPLE_FLOOR = 200


def to_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None


def load_games_master():
    path = os.path.join(PROCESSED_DIR, "games_master.csv")
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [r for r in csv.DictReader(f) if int(r["season"]) in TRAINING_SEASONS]


def load_elo():
    """homePregameElo/awayPregameElo live in raw games_{season}.csv, not
    games_master.csv - pull directly, pregame fields only, never postgame."""
    lookup = {}
    for season in TRAINING_SEASONS:
        path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                gid = r.get("id") or r.get("gameId")
                h_elo = to_float(r.get("homePregameElo"))
                a_elo = to_float(r.get("awayPregameElo"))
                lookup[(str(season), str(gid))] = (h_elo, a_elo)
    return lookup


def bet_result(bet_team, favorite, underdog, ats_result):
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


def percentile_index(sorted_vals, pct):
    """Same index-based method used throughout this project (never
    interpolated) - deterministic and reproducible across implementations."""
    n = len(sorted_vals)
    idx = min(int(n * pct / 100), n - 1)
    return sorted_vals[idx]


def main():
    print("Loading training-period data (2014-2021 only)...")
    games = load_games_master()
    verified = [g for g in games if g.get("market_data_quality_flag") == "verified"]
    elo = load_elo()
    print(f"  {len(games)} total training games, {len(verified)} Verified")
    print(f"  Elo data loaded for {len(elo)} games")

    # Build construction population: Verified, both teams' pregame Elo present,
    # closing_spread_final present, favorite/underdog resolvable
    construction = []
    for g in verified:
        season, gid = g["season"], g["game_id"]
        home, away = g["home_team"], g["away_team"]
        favorite, underdog = g.get("favorite"), g.get("underdog")
        closing = to_float(g.get("closing_spread_final"))
        h_elo, a_elo = elo.get((season, gid), (None, None))

        if not favorite or not underdog or closing is None or h_elo is None or a_elo is None:
            continue

        model_spread_home = (h_elo - a_elo) / 25.0
        market_spread_home = closing if favorite == home else -closing
        discrepancy = model_spread_home - market_spread_home

        construction.append({
            "season": int(season), "game_id": gid, "home": home, "away": away,
            "favorite": favorite, "underdog": underdog, "ats_result": g.get("ats_result"),
            "model_spread_home": round(model_spread_home, 3),
            "market_spread_home": round(market_spread_home, 3),
            "discrepancy": round(discrepancy, 3),
        })

    print(f"\n=== FLOOR 1: Construction population ===")
    print(f"  {len(construction)} games qualify (Verified + both Elo present + closing spread present)")
    print(f"  Required: >= {CONSTRUCTION_POPULATION_FLOOR}")

    if len(construction) < CONSTRUCTION_POPULATION_FLOOR:
        print(f"\n  ** BLOCKED: construction population {len(construction)} < {CONSTRUCTION_POPULATION_FLOOR}. **")
        print(f"  ** Cannot compute a threshold. Signal stays undefined, same status as Rivalry. **")
        write_result("BLOCKED", "construction population below 200-game floor", len(construction), 0)
        return
    print(f"  PASSES floor 1.")

    # Compute T = 75th percentile of |discrepancy|, single fixed rule, no candidates
    abs_discrepancies = sorted(abs(c["discrepancy"]) for c in construction)
    T = percentile_index(abs_discrepancies, 75)
    print(f"\n=== Threshold ===")
    print(f"  T = 75th percentile of |discrepancy| = {T:.3f}")

    if T == 0:
        print(f"\n  ** VALIDITY GATE TRIGGERED: T == 0 exactly. Signal invalid, fires for no game. **")
        write_result("BLOCKED", "T computed as exactly 0 (validity gate)", len(construction), 0)
        return

    # Triggered sample: |discrepancy| >= T
    triggered = [c for c in construction if abs(c["discrepancy"]) >= T]
    print(f"\n=== FLOOR 2: Triggered evaluation sample ===")
    print(f"  {len(triggered)} games trigger the signal (|discrepancy| >= {T:.3f})")
    print(f"  Required: >= {TRIGGERED_SAMPLE_FLOOR} (independent of floor 1)")

    if len(triggered) < TRIGGERED_SAMPLE_FLOOR:
        print(f"\n  ** BLOCKED: triggered sample {len(triggered)} < {TRIGGERED_SAMPLE_FLOOR}. **")
        print(f"  ** Threshold computable, but not enough games trigger it to evaluate. **")
        write_result("BLOCKED", f"triggered sample {len(triggered)} below 200-game floor", len(construction), len(triggered))
        return
    print(f"  PASSES floor 2. Proceeding to evaluation.")

    # Evaluate: positive discrepancy -> bet home; negative -> bet away
    results = []
    for c in triggered:
        bet_team = c["home"] if c["discrepancy"] > 0 else c["away"]
        r = bet_result(bet_team, c["favorite"], c["underdog"], c["ats_result"])
        if r:
            results.append((c["season"], r))

    n = len(results)
    wins = sum(1 for _, r in results if r == "win")
    losses = sum(1 for _, r in results if r == "loss")
    pushes = sum(1 for _, r in results if r == "push")
    decisions = wins + losses
    ats_pct = (wins / decisions * 100) if decisions else 0
    units = wins * UNIT_WIN + losses * UNIT_LOSS + pushes * UNIT_PUSH
    roi = (units / decisions * 100) if decisions else 0

    by_season = {}
    for season, r in results:
        by_season.setdefault(season, {"win": 0, "loss": 0, "push": 0})
        by_season[season][r] += 1
    stable_seasons = 0
    for season in TRAINING_SEASONS:
        s = by_season.get(season, {"win": 0, "loss": 0, "push": 0})
        s_dec = s["win"] + s["loss"]
        s_pct = (s["win"] / s_dec * 100) if s_dec else None
        if s_pct is not None and s_pct > SURVIVAL_SEASON_STABILITY_PCT:
            stable_seasons += 1

    survives = (ats_pct >= SURVIVAL_ATS_FLOOR) and (stable_seasons >= SURVIVAL_STABLE_SEASONS_NEEDED) and \
               (n >= TRIGGERED_SAMPLE_FLOOR)
    reason = "PASSES all §6.2 criteria" if survives else (
        f"ATS% {ats_pct:.1f} below {SURVIVAL_ATS_FLOOR}%" if ats_pct < SURVIVAL_ATS_FLOOR else
        f"only {stable_seasons}/8 seasons above {SURVIVAL_SEASON_STABILITY_PCT}%"
    )

    print(f"\n=== EVALUATION RESULT ===")
    print(f"  N={n}, Wins={wins}, Losses={losses}, Pushes={pushes}")
    print(f"  ATS%={ats_pct:.2f}, Units={units:.2f}, ROI={roi:.2f}%, Stable seasons={stable_seasons}/8")
    print(f"  Survives §6.2: {survives}")
    if not survives:
        print(f"  -> CUT: {reason}")

    write_result("REJECTED" if not survives else "SURVIVED", reason, len(construction), len(triggered),
                 n, wins, losses, pushes, ats_pct, units, roi, stable_seasons, survives)


def write_result(status, reason, construction_n, triggered_n,
                  n=None, wins=None, losses=None, pushes=None,
                  ats_pct=None, units=None, roi=None, stable_seasons=None, survives=None):
    path = os.path.join(PROCESSED_DIR, "model_vs_spread_result.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["status", "reason", "construction_population", "triggered_sample",
                          "n", "wins", "losses", "pushes", "ats_pct", "units", "roi_pct",
                          "stable_seasons_of_8", "survives_6_2"])
        writer.writerow([status, reason, construction_n, triggered_n,
                          n, wins, losses, pushes, ats_pct, units, roi, stable_seasons, survives])
    print(f"\nWrote {path}")
    print("Permanent record, same discipline as §15/§17 - not to be re-run with adjusted "
          "thresholds after seeing this result.")


if __name__ == "__main__":
    main()
