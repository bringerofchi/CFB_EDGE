"""
build_games_master.py
Phase 1A Step 4 — Build games_master.csv.

Per CFB Edge Lab Project Specification v1.5 Step 4:
  - closing_spread_final is NEVER silently chosen between disagreeing sources.
      Verified        -> use SBRO (documented choice: SBRO is the primary
                          source per spec §3.1, and Verified means the two
                          sources already agree within tolerance anyway)
      Source variance -> retain both, closing_spread_final = null (this is
                          usable data for sensitivity analysis via the raw
                          columns, but not appropriate as "the" number
                          without acknowledging the disagreement)
      Source conflict -> closing_spread_final = null, until manually
                          reviewed via odds_review_queue.csv
      Single source   -> use whichever source is actually present (not a
                          silent choice — there's no disagreement to hide)
      Missing         -> null

READ BEFORE TRUSTING THE FAVORITE/UNDERDOG FIELDS:
  Determining which team is favored requires a SIGNED spread. The
  reconciliation pipeline (line_reconciliation.py) works with unsigned
  magnitudes throughout (needed for difference-tolerance comparisons), so
  this script re-reads the raw CFBD lines JSON directly to recover sign.
  ASSUMPTION (not independently verified against CFBD's docs): negative
  spread = home team favored, positive = away team favored. This is the
  conventional meaning but has NOT been confirmed via a live schema check.
  This is exactly why the spec requires a manual spot-check sample (25
  wins, 25 losses, 10 pushes) before trusting ats_result at all — see the
  spot_check_sample.csv this script also produces. Do not treat ats_result
  as ground truth until that sample is manually verified.

Usage:
    python src/data_collection/build_games_master.py --seasons 2014-2025
"""

import argparse
import csv
import json
import os
import random

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "raw")
RAW_DIR = os.path.abspath(RAW_DIR)
PROCESSED_DIR = os.path.abspath(os.path.join(RAW_DIR, "..", "processed"))


def load_games(season):
    path = os.path.join(RAW_DIR, "games", f"games_{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def load_reconciled(season):
    path = os.path.join(PROCESSED_DIR, f"lines_reconciled_{season}.csv")
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return {row["game_id"]: row for row in csv.DictReader(f)}


def load_signed_cfbd_spreads(season):
    """Re-read raw CFBD lines JSON directly to recover the SIGNED spread,
    lost during reconciliation's abs()-based magnitude comparisons. Returns
    both close and open (signed, same convention: negative = home favored)
    since Signal 3 (Market Movement Confirmation) needs direction, not just
    magnitude — a movement calculation that loses sign can't tell you
    whether the line moved toward the home or away team."""
    path = os.path.join(RAW_DIR, "lines", "cfbd", f"lines_{season}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    games = payload.get("data", payload)
    signed = {}
    for g in games:
        game_id = g.get("id") or g.get("gameId")
        lines = g.get("lines", [])
        preferred = [l for l in lines if (l.get("provider") or "").lower() in
                     ("consensus", "draftkings", "bovada")]
        pool = preferred if preferred else lines
        closes = [float(l["spread"]) for l in pool if l.get("spread") is not None]
        opens = [float(l["spreadOpen"]) for l in pool if l.get("spreadOpen") is not None]
        entry = {}
        if closes:
            entry["close"] = sum(closes) / len(closes)
        if opens:
            entry["open"] = sum(opens) / len(opens)
        if entry:
            signed[str(game_id)] = entry
    return signed


def compute_ats(home_team, away_team, home_score, away_score, signed_cfbd_spread, closing_spread_final):
    """Returns (favorite, underdog, favorite_cover, ats_result).
    ASSUMPTION: negative signed spread = home favored. See module docstring."""
    if signed_cfbd_spread is None or closing_spread_final is None:
        return (None, None, None, "no_line")
    if home_score is None or away_score is None or home_score == "" or away_score == "":
        return (None, None, None, "no_score")

    home_score, away_score = float(home_score), float(away_score)
    margin = home_score - away_score  # positive = home won by this much

    if signed_cfbd_spread < 0:
        favorite, underdog = home_team, away_team
        favorite_margin = margin  # home is favorite; positive margin = favorite won
    else:
        favorite, underdog = away_team, home_team
        favorite_margin = -margin  # away is favorite; away winning = negative home margin

    cover_line = abs(closing_spread_final)
    if favorite_margin > cover_line:
        result = "favorite_cover"
    elif favorite_margin < cover_line:
        result = "underdog_cover"
    else:
        result = "push"

    return (favorite, underdog, result == "favorite_cover", result)


def build_season(season):
    games = load_games(season)
    reconciled = load_reconciled(season)
    signed_spreads = load_signed_cfbd_spreads(season)

    rows = []
    for g in games:
        game_id = g.get("id") or g.get("gameId") or ""
        home_team = g.get("homeTeam") or g.get("home_team") or ""
        away_team = g.get("awayTeam") or g.get("away_team") or ""
        home_score = g.get("homePoints") or g.get("home_points") or ""
        away_score = g.get("awayPoints") or g.get("away_points") or ""
        week = g.get("week") or ""
        date = (g.get("startDate") or g.get("start_date") or "")[:10]

        rec = reconciled.get(str(game_id), {})
        flag = rec.get("market_data_quality_flag", "missing")
        def _to_float(v):
            if v in (None, "", "None"):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        sbro_close = _to_float(rec.get("sbro_closing_spread"))
        cfbd_close = _to_float(rec.get("cfbd_closing_spread"))
        diff = _to_float(rec.get("closing_spread_difference"))

        # Explicit, non-silent closing_spread_final logic (spec Step 4)
        if flag == "verified":
            closing_spread_final = sbro_close  # documented choice: SBRO is primary source
        elif flag == "single_source":
            closing_spread_final = sbro_close if sbro_close else cfbd_close
        else:  # source_variance, source_conflict, missing
            closing_spread_final = None

        cfbd_signed = signed_spreads.get(str(game_id), {})
        signed_spread = cfbd_signed.get("close")  # used for favorite/underdog, as before
        signed_open = cfbd_signed.get("open")

        # OPENING SPREAD: promoted from validation (this session) — SBRO is
        # now the PRIMARY source for 2014-2022, validated via
        # validate_opening_lines.py (829 cross-validated games, mean error
        # 1.08 pts after the resolve_line() sanity-check fix; 1 residual
        # flagged case fully explained, already excluded via source_conflict
        # on that game's closing line — see spec discussion, not a new bug).
        # CFBD's own opening data is the fallback ONLY (2023-2025, where
        # SBRO has no coverage at all, or any game SBRO didn't resolve).
        sbro_open_magnitude = _to_float(rec.get("sbro_opening_spread"))
        opening_source = None
        opening_spread = None
        signed_sbro_open = None

        if sbro_open_magnitude is not None and signed_spread is not None:
            # Apply the same favorite-direction sign as the closing spread.
            # ASSUMPTION: the favorite doesn't flip between open and close —
            # true the large majority of the time; rare "steam" reversals
            # are an accepted simplification, not corrected for here.
            signed_sbro_open = -sbro_open_magnitude if signed_spread < 0 else sbro_open_magnitude
            opening_spread = sbro_open_magnitude
            opening_source = "sbro"
        elif signed_open is not None:
            opening_spread = abs(signed_open)
            opening_source = "cfbd"

        # Line movement: SAME-SOURCE pairs preferred (SBRO open -> SBRO
        # close) per explicit decision — avoids mixing providers, which
        # could look like "movement" that's actually just cross-book
        # disagreement. CFBD-only pair is the fallback.
        #
        # BUG FIX: previously gated on flag == "verified" only, which
        # excluded source_variance games from movement calculation even
        # though §3.1 treats Verified + Source Variance as the legitimate
        # combined population for sensitivity analysis — this was more
        # restrictive than the design intends. source_conflict is still
        # excluded deliberately: those games' sbro_close is the tier most
        # likely to reflect a genuine parsing error (§11), so trusting an
        # sbro_open->sbro_close movement built on top of an already-flagged-
        # unreliable close would compound that unreliability, not just
        # inherit it.
        line_movement_signed = None
        movement_source = None
        if signed_sbro_open is not None and flag in ("verified", "source_variance") and sbro_close is not None:
            signed_sbro_close = -sbro_close if signed_spread < 0 else sbro_close
            line_movement_signed = round(signed_sbro_close - signed_sbro_open, 2)
            movement_source = "sbro_same_source"
        elif signed_spread is not None and signed_open is not None:
            line_movement_signed = round(signed_spread - signed_open, 2)
            movement_source = "cfbd_same_source"

        winner = None
        if home_score not in ("", None) and away_score not in ("", None):
            try:
                hs, aws = float(home_score), float(away_score)
                winner = home_team if hs > aws else (away_team if aws > hs else "tie")
            except ValueError:
                pass

        favorite, underdog, favorite_cover, ats_result = compute_ats(
            home_team, away_team, home_score, away_score, signed_spread, closing_spread_final
        )

        rows.append({
            "game_id": game_id,
            "season": season,
            "week": week,
            "date": date,
            "home_team": home_team,
            "away_team": away_team,
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "opening_spread": opening_spread,
            "opening_spread_source": opening_source,
            "line_movement_source": movement_source,
            "closing_spread_sbro": sbro_close,
            "closing_spread_cfbd": cfbd_close,
            "closing_spread_final": closing_spread_final,
            "closing_spread_difference": diff,
            "line_movement_signed": line_movement_signed,
            "market_data_quality_flag": flag,
            "favorite": favorite,
            "underdog": underdog,
            "favorite_cover": favorite_cover,
            "ats_result": ats_result,
        })
    return rows


def write_spot_check_sample(all_rows, path, seed=42):
    """25 favorite_cover, 25 underdog_cover, 10 push — for MANUAL verification
    against a known source, per spec Step 4. This script cannot verify its
    own output; a human must check these against real results.

    SAFETY: if a spot-check file already exists AND already has manual
    verification filled in (manually_verified_correct is non-empty for at
    least one row), do NOT overwrite it — rebuilding games_master.csv for
    an unrelated reason (e.g. adding a new column) should never silently
    destroy completed manual review work. Write to a .new file instead and
    tell the person to compare/merge manually."""
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            existing = list(csv.DictReader(f))
        already_verified = any((r.get("manually_verified_correct") or "").strip() for r in existing)
        if already_verified:
            path = path.replace(".csv", ".new.csv")
            print(f"  ** NOTE: existing spot_check_sample.csv already has verification filled in. "
                  f"Writing the newly-generated sample to {os.path.basename(path)} instead of "
                  f"overwriting it — compare the two and merge manually if needed. **")

    rng = random.Random(seed)
    wins = [r for r in all_rows if r["ats_result"] == "favorite_cover"]
    losses = [r for r in all_rows if r["ats_result"] == "underdog_cover"]
    pushes = [r for r in all_rows if r["ats_result"] == "push"]

    sample = (rng.sample(wins, min(25, len(wins))) +
              rng.sample(losses, min(25, len(losses))) +
              rng.sample(pushes, min(10, len(pushes))))

    if not sample:
        print("No rows with a valid ats_result to sample — skipping spot-check file.")
        return

    with open(path, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(sample[0].keys()) + ["manually_verified_correct", "verification_notes"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sample:
            r = dict(r)
            r["manually_verified_correct"] = ""
            r["verification_notes"] = ""
            writer.writerow(r)
    print(f"Wrote {len(sample)} rows to {path} for MANUAL spot-check "
          f"({len(sample) and min(25, len(wins))} favorite covers, "
          f"{min(25, len(losses))} underdog covers, {min(10, len(pushes))} pushes)")


def main():
    parser = argparse.ArgumentParser(description="Phase 1A Step 4 — build games_master.csv.")
    parser.add_argument("--seasons", default="2014-2025")
    args = parser.parse_args()

    if "-" in args.seasons:
        start, end = args.seasons.split("-")
        seasons = list(range(int(start), int(end) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    all_rows = []
    for season in seasons:
        rows = build_season(season)
        all_rows.extend(rows)
        n_final = sum(1 for r in rows if r["closing_spread_final"])
        print(f"Season {season}: {len(rows)} games, {n_final} with a usable closing_spread_final")

    out_path = os.path.join(PROCESSED_DIR, "games_master.csv")
    if all_rows:
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nWrote {len(all_rows)} total games to {out_path}")

        spot_check_path = os.path.join(PROCESSED_DIR, "..", "..", "analysis", "validation", "spot_check_sample.csv")
        os.makedirs(os.path.dirname(spot_check_path), exist_ok=True)
        write_spot_check_sample(all_rows, spot_check_path)
    else:
        print("No games found — check that cfbd_pull.py and line_reconciliation.py have been run.")

    print("\nNext: manually verify spot_check_sample.csv against a known source, "
          "then run data_quality_report.py before proceeding to features (spec §13 gate).")


if __name__ == "__main__":
    main()
