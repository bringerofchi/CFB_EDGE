# CFB Edge Lab

CFB Edge Lab is a college-football market research framework. It collects historical game, line, team, personnel, and situational inputs; creates reproducible features; evaluates frozen ATS hypotheses on a protected training window; and contains a separate live odds-collection path. It is not an automated betting system.

## Research design

The core evaluation hard-locks its training period to **2014–2021**. The code cannot be pointed at 2022–2025 by a runtime flag, protecting the future test window from accidental inspection during signal construction.

Core signal survival requires:

- At least 200 observations for a primary signal
- At least 52.4% ATS
- More than 50% ATS in at least six of eight seasons

> **Verification note:** confirmed directly against `src/model/signal_library.py` (`SURVIVAL_MIN_GAMES_PRIMARY = 200`, `SURVIVAL_ATS_FLOOR = 52.4`, `SURVIVAL_SEASON_STABILITY_PCT = 50.0` with `SURVIVAL_STABLE_SEASONS_NEEDED = 6` of 8) and consistent with the `reason_if_cut` text in the generated `signal_evaluation_summary.csv`. The governing spec document (`CFB_Edge_Lab_Project_Spec.md`, last known ~v2.8) is still missing from disk, so these numbers are verified against the running code, not against the spec's source-of-truth text — recover the spec if an independent check against it is needed.

The original library evaluates hidden-efficiency underdogs, experienced-QB underdogs at several thresholds, market-movement confirmation, and transfer-volatility signals. A separate 2A library evaluates nine additional frozen candidates. Results are records of evidence, including cut signals — not a menu for post-hoc selection.

## Pipeline

The rebuild workflow can collect 2014–2025 CFBD game, line, PPA, advanced-stat, roster, recruiting, coach, and venue data; import historical closing-line material; reconcile lines; build a game universe and master dataset; create efficiency, situational, personnel, and market features; run quality checks; and generate signal evaluations.

The repository also contains focused totals, trap-game, rivalry, opening-line, model-vs-spread, and reconciliation scripts, plus a live collector scheduler.

## Data artifacts

Research data is file-oriented: raw pulls, processed feature tables, generated signal libraries, and audit CSVs. The current repository has `data/raw`, `data/processed`, `live`, `src`, and a couple of top-level result CSVs (`totals_reconciliation_detail.csv`, `trapgame_candidate_b_result.csv`).

The core research pipeline (`raw`, `processed`, generated CSVs) is file-oriented and should not be described as a database-backed project. The separate `live` path is the one exception: the live odds collector (Phase 4) already stores snapshots in **SQLite**, with a never-overwrite guarantee and tiered polling cadence. So: file-oriented for research/signal evaluation, SQLite for the live-odds collection path — don't conflate the two when describing the repo.

Before claiming current performance, extract and review the generated CSV outputs: game counts, verified-line coverage, training/test separation, signal flags, ATS outcomes, exclusions, and reconciliation exceptions.

## Current operational cautions

- The rebuild makes real API calls and may consume CFBD quota.
- The scripts' expected `data/raw` and `data/processed` paths (e.g. referenced in `src/features/efficiency_features.py`, `src/model/audit_rivalry_coverage.py`) match the actual on-disk layout as of this check.
- A manual data-quality spot check remains part of the documented gate.
- **Data loss (resolved):** a failed zip extraction on the Windows project machine (`C:\Projects\CFB EDGE\college-football-edge-lab\`) previously wiped the `data\` tree. `data\raw\` (coaches, games, lines, roster, stats, venues) and `data\processed\` (including `games_master.csv`, 10,375 rows, and the reconciled per-season line files) are populated again as of this check. The governing project spec (`CFB_Edge_Lab_Project_Spec.md`) is still missing from disk — its absence no longer blocks reading current performance from the CSVs, but any claim that depends on the spec's exact wording (rather than the code's behavior) still can't be independently checked.
- This directory is not a git repository (no `.git`), so none of the above is currently version-controlled or backed up by git history — treat local files as the only copy until this is put under source control.
- There is no basis here to claim a live 2026 model or production-grade recommendations without a fresh review of generated outputs; `signal_evaluation_summary.csv`/`signal_evaluation_summary_2a.csv` currently show all evaluated primary/2A signals failing the survival floor (see `reason_if_cut`), so there is no currently-surviving signal to promote.

## Future AAR use

The cross-project research extract should preserve event ID, season/week, source and collection time, opening/closing price, feature values, model/signal version, qualification state, ATS result, and reconciliation/quality flags.
