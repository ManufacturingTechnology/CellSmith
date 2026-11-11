@echo off
REM Run only the CI-eligible tests (Windows). Mirrors `make test-ci`.
REM
REM Deselects @pytest.mark.local_only -- anything needing a real display, GPU
REM driver, or interactive input. NOTE THE POLARITY: a test is CI-eligible BY
REM DEFAULT and must opt out, so a forgotten marker fails loudly in CI rather
REM than silently never running.
REM
REM LIBGL_ALWAYS_SOFTWARE mirrors the Linux container settings so the two
REM platforms exercise the same code path as closely as Windows allows.
REM
REM Extra pytest args pass straight through:  test-ci.bat -x
setlocal

set QT_QPA_PLATFORM=offscreen
set LIBGL_ALWAYS_SOFTWARE=1

call :find_conda
if "%CONDA_EXE%"=="" (
    echo [test-ci] ERROR: could not locate conda.exe. Set CONDA_EXE or add conda to PATH.
    exit /b 1
)

"%CONDA_EXE%" run --no-capture-output -n CellSmithEnv python -m pytest -m "not local_only" %*
exit /b %ERRORLEVEL%

:find_conda
if not "%CONDA_EXE%"=="" exit /b 0
where conda.exe >nul 2>&1 && (for /f "delims=" %%i in ('where conda.exe') do set "CONDA_EXE=%%i" & exit /b 0)
if exist "%LOCALAPPDATA%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%LOCALAPPDATA%\anaconda3\Scripts\conda.exe" & exit /b 0
if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\anaconda3\Scripts\conda.exe" & exit /b 0
if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_EXE=%USERPROFILE%\miniconda3\Scripts\conda.exe" & exit /b 0
if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDA_EXE=%ProgramData%\anaconda3\Scripts\conda.exe" & exit /b 0
exit /b 0
