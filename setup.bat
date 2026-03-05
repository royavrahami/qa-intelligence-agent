@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM QA Intelligence Agent – One-command setup for Windows
REM Usage: Double-click setup.bat  OR  run in Command Prompt / PowerShell
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo =====================================================
echo    QA Intelligence Agent - Windows Setup
echo =====================================================
echo.

REM ── Python check ─────────────────────────────────────────────────────────────
echo [1/5] Checking Python...
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found.
    echo Download from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
python --version
echo OK

REM ── Virtual environment ───────────────────────────────────────────────────────
echo.
echo [2/5] Creating virtual environment...
IF NOT EXIST ".venv" (
    python -m venv .venv
    echo Created .venv\
) ELSE (
    echo .venv already exists
)

REM ── Activate and install ──────────────────────────────────────────────────────
echo.
echo [3/5] Installing dependencies (1-2 minutes)...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
echo Dependencies installed.

REM ── .env setup ────────────────────────────────────────────────────────────────
echo.
echo [4/5] Setting up configuration...
IF NOT EXIST ".env" (
    copy .env.example .env >nul
    echo.
    echo ┌──────────────────────────────────────────────────────┐
    echo │  ACTION REQUIRED                                     │
    echo │  Edit the .env file and add your OpenAI API key     │
    echo │  OPENAI_API_KEY=sk-proj-...                         │
    echo └──────────────────────────────────────────────────────┘
    echo.
    echo Opening .env in Notepad...
    
    REM Write default .env content
    (
        echo OPENAI_API_KEY=PASTE_YOUR_KEY_HERE
        echo OPENAI_MODEL=gpt-4o
        echo OPENAI_MAX_TOKENS=2000
        echo DATABASE_URL=sqlite:///./data/qa_agent.db
        echo SCHEDULE_INTERVAL_HOURS=6
        echo MIN_RELEVANCE_SCORE=40
        echo REPORTS_DIR=./reports
        echo LOG_LEVEL=INFO
        echo LOG_DIR=./logs
    ) > .env
    
    notepad .env
    echo After saving .env, press any key to continue...
    pause >nul
) ELSE (
    echo .env already exists ^(not overwritten^)
)

REM ── Create directories ────────────────────────────────────────────────────────
IF NOT EXIST "data" mkdir data
IF NOT EXIST "reports" mkdir reports
IF NOT EXIST "logs" mkdir logs

REM ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo =====================================================
echo   Setup complete!
echo =====================================================
echo.
echo [5/5] How to run:
echo.
echo   Activate environment (run each time you open a terminal):
echo     .venv\Scripts\activate
echo.
echo   Run once (generates a report and exits):
echo     python main.py run
echo.
echo   Run every 6 hours automatically:
echo     python main.py schedule
echo.
echo   View run history:
echo     python main.py status
echo.
echo   Reports are saved to: %CD%\reports\
echo.
pause
