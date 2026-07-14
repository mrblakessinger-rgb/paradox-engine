@echo off
title Proof A — Agent Fleet
cd /d "%~dp0"
echo.
echo  Proof A: Agent fleet under random tool failures
echo.
where python >nul 2>&1 && set PY=python || set PY=py -3
%PY% run_proof_a.py
echo.
if exist "out\proof_a_case_study.html" start "" "%CD%\out\proof_a_case_study.html"
if exist "out\proof_a_comparison.png" start "" "%CD%\out\proof_a_comparison.png"
echo.
pause
