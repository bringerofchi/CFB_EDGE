@echo off
title CFB Edge Lab - Candidate B Evaluation (Trap Game)
color 0A
echo ============================================================
echo   Evaluating the FROZEN Candidate B signal (threshold=31.00)
echo   against training data (2014-2021 ONLY - hardcoded)
echo ============================================================
python src\model\trapgame_signal.py
echo.
echo ============================================================
echo   Done. Wrote trapgame_candidate_b_result.csv
echo   This is a PERMANENT RECORD - paste console output back
echo   to Claude, whatever it shows.
echo ============================================================
pause
