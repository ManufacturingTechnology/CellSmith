@echo off
REM Run the FULL test suite (Windows). Mirrors `make test`.
REM
REM Includes tests marked local_only (real display / GPU driver / interaction).
REM QT_QPA_PLATFORM=offscreen is also set in tests/conftest.py before Qt is
REM imported; it is set here too so behavior matches a bare pytest invocation.
REM
REM Extra pytest args pass straight through:  test.bat -k font -vv
setlocal

set QT_QPA_PLATFORM=offscreen

call :find_conda
if "%CONDA_EXE%"=="" (
    echo [test] ERROR: could not locate conda.exe. Set CONDA_EXE or add conda to PATH.
    exit /b 1
)

"%CONDA_EXE%" run --no-capture-output -n CellSmithEnv python -m pytest %*
exit /b %ERRORLEVEL%

:find_conda
if not "%CONDA_EXE%"=="" exit /b 0
where conda.exe >nul 2>&1 && (for /f "delims=" %%i in ('where conda.exe') do set "CONDA_EXE=%%i" & exit /b 0)
if exist "%LOCALAPPDATA%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%LOCALAPPDATA%\anaconda3\Scripts\conda.exe" & exit /b 0
if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe" & exit /b 0
if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe" & exit /b 0
if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%ProgramData%\anaconda3\Scripts\conda.exe" & exit /b 0
exit /b 0
