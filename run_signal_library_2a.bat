@echo off
title CFB Edge Lab - Phase 2A Signal Evaluation
color 0A
echo ============================================================
echo   Evaluating the 9 frozen Phase 2A candidates against
echo   training data (2014-2021 ONLY - hardcoded)
echo ============================================================
python src\model\signal_library_2a.py
echo.
echo ============================================================
echo   Done. Wrote data\processed\signal_evaluation_summary_2a.csv
echo   Paste the console output back to Claude.
echo ============================================================
pause
