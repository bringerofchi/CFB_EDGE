@echo off
title CFB Edge Lab - Model-vs-Spread Discrepancy Evaluation
color 0A
echo ============================================================
echo   Evaluating the frozen Model-vs-Spread Discrepancy signal
echo   (spec Section 18) against training data (2014-2021 ONLY)
echo ============================================================
python src\model\model_vs_spread_signal.py
echo.
echo ============================================================
echo   Done. Wrote data\processed\model_vs_spread_result.csv
echo   Paste the console output back to Claude.
echo ============================================================
pause
