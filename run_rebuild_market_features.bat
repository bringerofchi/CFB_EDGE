@echo off
title CFB Edge Lab - Rebuild Market Features (with new movement data)
color 0A
echo Rebuilding market features with the newly-promoted SBRO opening/movement data
python src\features\market_features.py --seasons 2014-2021
echo.
echo Done. line_movement_toward_team should now be populated for 2014-2020 too.
pause
