@echo off

:: Change to the directory where this script lives
cd /d "%~dp0"

call dev.bat no_pause || (
    echo Error: Could not dev
    pause
    exit /b %ERRORLEVEL%
)

echo Running src/main.py...
:: Forward any extra args (e.g. a .step file path) through to the app
call conda run --no-capture-output -n CellSmithEnv python -m src.main %* || (
    echo Error: Could not run src/main.py
    pause
    exit /b %ERRORLEVEL%
)
echo Ran src/main.py

:: Pause if no args were specified
IF "%~1"=="" (
    pause
)
