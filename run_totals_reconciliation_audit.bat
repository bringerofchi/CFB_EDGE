@echo off
title CFB Edge Lab - Totals Reconciliation Audit
color 0A
echo ============================================================
echo   Totals market data-quality audit (NOT outcome evaluation)
echo   Runs across all pulled seasons for reconciliation, but
echo   only reports the tolerance-tier distribution from 2014-2021
echo ============================================================
python src\data_collection\totals_reconciliation_audit.py --seasons 2014-2025
echo.
echo ============================================================
echo   Done. Wrote totals_reconciliation_detail.csv in the folder
echo   you ran this from. Paste the console output back to Claude.
echo ============================================================
pause
