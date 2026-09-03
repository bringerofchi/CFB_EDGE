@echo off
title CFB Edge Lab - Phase 4 Setup
color 0B
echo ============================================================
echo   Phase 4 Live Collector - One-time setup
echo ============================================================

if "%ODDS_API_KEY%"=="" (
    echo Need your the-odds-api.com API key - sign up free at
    echo https://the-odds-api.com/
    echo.
    set /p ODDS_API_KEY="Paste it here and press Enter: "
)

echo.
echo Creating database schema...
python live\collector\db_schema.py

echo.
echo ============================================================
echo   Setup complete. Database created at live\data\live_odds.db
echo   Next: run run_phase4_scheduler.bat to start collection.
echo   IMPORTANT: set ODDS_API_KEY permanently (not just this
echo   session) via: setx ODDS_API_KEY your_key_here
echo ============================================================
pause
