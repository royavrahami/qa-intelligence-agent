@echo off
SET PYTHONNOUSERSITE=1
call "C:\Users\Roy Avrahami\agents\quality-manager-intelligence-agent\.venv\Scripts\activate.bat"
python main.py %*
