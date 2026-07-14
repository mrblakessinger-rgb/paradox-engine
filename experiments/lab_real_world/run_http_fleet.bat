@echo off
cd /d "%~dp0\.."
python real_world\http_fleet_demo.py
if errorlevel 1 pause
start "" "real_world\out\http_fleet_case_study.html"
