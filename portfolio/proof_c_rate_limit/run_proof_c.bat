@echo off
cd /d "%~dp0"
python run_proof_c.py
if errorlevel 1 pause
start "" "out\proof_c_case_study.html"
