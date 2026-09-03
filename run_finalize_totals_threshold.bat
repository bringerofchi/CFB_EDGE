@echo off
title CFB Edge Lab - Finalize Totals Threshold
color 0A
echo ============================================================
echo   IMPORTANT: run this from src\model\ (needs
echo   totals_reconciliation_detail.csv in the SAME folder -
echo   run run_totals_reconciliation_audit.bat first if you
echo   haven't, then copy/move that CSV into src\model\)
echo ============================================================
cd src\model
python finalize_totals_threshold.py
cd ..\..
echo.
echo ============================================================
echo   Done. Paste console output back to Claude for review
echo   before this threshold gets frozen.
echo ============================================================
pause
