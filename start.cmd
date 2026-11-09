@echo off
title Claude Ses
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m server.app --open
if errorlevel 1 pause
