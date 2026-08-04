@echo off

:: Change to the directory where this script lives
cd /d "%~dp0"

:: Ensure conda is available
where conda >nul 2>nul
IF ERRORLEVEL 1 (
    echo Error: conda not found on PATH. Install Miniconda/Miniforge and open an Anaconda Prompt.
    goto :fail
)

:: If the env already exists, nothing to do
call conda env list | findstr /R /C:"^CellSmithEnv " >nul 2>nul
IF %ERRORLEVEL%==0 (
    echo conda env "CellSmithEnv" already exists
    goto :done
)

:: Guard: a second concurrent env-create against the same directory corrupts the
:: half-built env (conda "Cannot link a source that does not exist").
IF EXIST ".env_setup.lock" (
    echo Error: another env setup appears to be running - .env_setup.lock exists.
    echo If you are sure none is running, delete .env_setup.lock and retry.
    goto :fail
)

echo locked> ".env_setup.lock"
echo Creating conda env "CellSmithEnv" from packaging/environment.yml...
call conda env create -f packaging/environment.yml
IF ERRORLEVEL 1 (
    del ".env_setup.lock" >nul 2>nul
    echo Error: Could not create conda env "CellSmithEnv"
    goto :fail
)
del ".env_setup.lock" >nul 2>nul
echo Created conda env "CellSmithEnv"

:done
echo Set up for development successfully
:: Pause if arg not specified
IF "%~1"=="" pause
exit /b 0

:fail
pause
exit /b 1
