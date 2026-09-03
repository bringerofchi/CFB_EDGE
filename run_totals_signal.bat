@echo off
title CFB Edge Lab - Candidate A Evaluation (Totals Market Inefficiency)
color 0A
echo ============================================================
echo   Evaluating the FROZEN Candidate A signal (threshold=5.59)
echo   against training data (2014-2021 ONLY - hardcoded)
echo   Needs totals_reconciliation_detail.csv in src\model\
echo ============================================================
cd src\model
python totals_signal.py
cd ..\..
echo.
echo ============================================================
echo   Done. Wrote totals_candidate_a_result.csv
echo   This is a PERMANENT RECORD - paste console output back
echo   to Claude, whatever it shows.
echo ============================================================
pause
