# CFB Edge Lab

CFB Edge Lab is a college-football market research framework. It collects historical game, line, team, personnel, and situational inputs; creates reproducible features; evaluates frozen ATS hypotheses on a protected training window; and contains a separate live odds-collection path. It is not an automated betting system.

## Research design

The core evaluation hard-locks its training period to **2014–2021**. The code cannot be pointed at 2022–2025 by a runtime flag, protecting the future test window from accidental inspection during signal construction.

Core signal survival requires:

- At least 200 observations for a primary signal
- At least 52.4% ATS
- More than 50% ATS in at least six of eight seasons

> **Verification note:** these three thresholds are stated here from memory. The governing spec document (`CFB_Edge_Lab_Project_Spec.md`, last known ~v2.8) is currently missing from disk (see Data-loss note below) and has not yet been recovered or reconstructed. Treat these numbers as unconfirmed against source-of-truth until the spec is recovered and they've been checked against it.

The original library evaluates hidden-efficiency underdogs, experienced-QB underdogs at several thresholds, market-movement confirmation, and transfer-volatility signals. A separate 2A library evaluates nine additional frozen candidates. Results are records of evidence, including cut signals — not a menu for post-hoc selection.

## Pipeline

The rebuild workflow can collect 2014–2025 CFBD game, line, PPA, advanced-stat, roster, recruiting, coach, and venue data; import historical closing-line material; reconcile lines; build a game universe and master dataset; create efficiency, situational, personnel, and market features; run quality checks; and generate signal evaluations.

The repository also contains focused totals, trap-game, rivalry, opening-line, model-vs-spread, and reconciliation scripts, plus a live collector scheduler.

## Data artifacts

Research data is file-oriented: raw pulls, processed feature tables, generated signal libraries, and audit CSVs. The current repository has `raw`, `processed`, `live`, `src`, and several top-level result CSVs.

The core research pipeline (`raw`, `processed`, generated CSVs) is file-oriented and should not be described as a database-backed project. The separate `live` path is the one exception: the live odds collector (Phase 4) already stores snapshots in **SQLite**, with a never-overwrite guarantee and tiered polling cadence. So: file-oriented for research/signal evaluation, SQLite for the live-odds collection path — don't conflate the two when describing the repo.

Before claiming current performance, extract and review the generated CSV outputs: game counts, verified-line coverage, training/test separation, signal flags, ATS outcomes, exclusions, and reconciliation exceptions.

## Current operational cautions

- The rebuild makes real API calls and may consume CFBD quota.
- The scripts' expected `data/raw` and `data/processed` paths must be reconciled with the committed folder layout before a clean setup claim is made.
- A manual data-quality spot check remains part of the documented gate.
- **Data loss (unresolved):** a failed zip extraction on the Windows project machine (`C:\Projects\CFB EDGE\college-football-edge-lab\`) wiped the `data\` tree — no `raw\`, no `interim\`, no `games_master.csv`, no season-level CSVs — and the governing project spec was not found on disk either. Pipeline source under `src\` survived intact. Until this is resolved (backup located, or re-derivation done with explicit sign-off), the CSV outputs referenced above for "current performance" claims may not currently exist, and the spec-derived thresholds above are unverified.
- There is no basis here to claim a live 2026 model, a profitable surviving signal, or production-grade recommendations without a fresh review of generated outputs.

## Future AAR use

The cross-project research extract should preserve event ID, season/week, source and collection time, opening/closing price, feature values, model/signal version, qualification state, ATS result, and reconciliation/quality flags.
