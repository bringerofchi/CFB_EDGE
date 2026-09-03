@echo off
title CFB Edge Lab - Live Odds Scheduler (KEEP THIS WINDOW OPEN)
color 0A
echo ============================================================
echo   Starting the live odds scheduler.
echo   This window must stay open for collection to continue.
echo   Recommended: also set up via Windows Task Scheduler to
echo   auto-restart on logon/reboot (see spec section 24).
echo   Press Ctrl+C to stop.
echo ============================================================
python live\collector\scheduler.py
pause
