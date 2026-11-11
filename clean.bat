@echo off

:: Change to the directory where this script lives
cd /d "%~dp0"

:: Remove the conda environment if it exists
call conda env list | findstr /R /C:"^CellSmithEnv " >nul 2>nul
IF %ERRORLEVEL%==0 (
    echo Removing conda env "CellSmithEnv"...
    call conda env remove -n CellSmithEnv -y || (
        echo Error: Could not remove conda env "CellSmithEnv"
        pause
        exit /b %ERRORLEVEL%
    )
    echo Removed conda env "CellSmithEnv"
) ELSE (
    echo conda env "CellSmithEnv" does not exist
)

echo Clean completed successfully
:: Pause if arg not specified
IF "%~1"=="" (
    pause
)
