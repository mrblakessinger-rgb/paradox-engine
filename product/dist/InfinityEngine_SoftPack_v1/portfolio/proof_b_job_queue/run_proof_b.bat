@echo off
title Proof B — Job Queue
cd /d "%~dp0"
where python >nul 2>&1 && set PY=python || set PY=py -3
%PY% run_proof_b.py
if exist "out\proof_b_case_study.html" start "" "%CD%\out\proof_b_case_study.html"
pause
