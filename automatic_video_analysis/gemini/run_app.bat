@echo off
title Fable Volleyball Scout App
cd /d "%~dp0..\.."
".\automatic_video_analysis\gemini\.venv\Scripts\python.exe" -m automatic_video_analysis.gemini.app
pause
