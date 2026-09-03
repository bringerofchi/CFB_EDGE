@echo off
title CFB Edge Lab - Opening Line Validation
color 0A

echo ============================================================
echo   Step A: Re-running reconciliation with opening-line
echo   resolution added (shared resolver, open + close)
echo ============================================================
python src\data_collection\line_reconciliation.py --seasons 2014-2025

echo.
echo ============================================================
echo   Step B: Validating opening-line accuracy
echo   (NOT promoting to production yet - validation only)
echo ============================================================
python src\data_collection\validate_opening_lines.py --seasons 2014-2021

echo.
echo ============================================================
echo   Done. Read the RECOMMENDATION section carefully.
echo   Check analysis\validation\opening_line_suspicious_cases.csv
echo   Paste the full output back to Claude.
echo ============================================================
pause
