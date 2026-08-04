@echo off
:: Build the Windows onedir distributable:
::   dist\CellSmith\                        the app folder (CellSmith.exe launcher)
::   dist\CellSmith-v<version>-win64.zip    the distribution archive
:: Optional arg suppresses the final pause (for CI):  build.bat ci

:: Change to the directory where this script lives
cd /d "%~dp0"

:: Ensure the conda env exists (no-op if already created)
call "%~dp0dev.bat" no_pause
IF ERRORLEVEL 1 goto :fail

:: Ensure PyInstaller is present (dev.bat skips env UPDATE when the env already
:: exists, so an older env may predate pyinstaller landing in packaging/environment.yml).
call conda run --no-capture-output -n CellSmithEnv python -m pip install --quiet "pyinstaller>=6.10"
IF ERRORLEVEL 1 goto :fail

:: Ensure the mesh-import deps are present (dev.bat skips env UPDATE for an
:: existing env, so an older env may predate them landing in packaging/environment.yml).
:: These back the ADDITIVE mesh path (subordinate to STEP); all ship cp312 wheels.
call conda run --no-capture-output -n CellSmithEnv python -m pip install --quiet trimesh mapbox_earcut scipy shapely
IF ERRORLEVEL 1 goto :fail
:: manifold3d is OPTIONAL (trimesh's boolean backend). Try the wheel; if none
:: exists (future python/arch), retry with the parallel backend disabled (the
:: sibling coprocessor workaround). NON-fatal - the slicer falls back to native.
call conda run --no-capture-output -n CellSmithEnv python -m pip install --quiet manifold3d || call conda run --no-capture-output -n CellSmithEnv python -m pip install --quiet manifold3d --config-settings=cmake.args="-DMANIFOLD_PAR=NONE"

:: Freeze (onedir; see packaging/cellsmith.spec)
call conda run --no-capture-output -n CellSmithEnv python -m PyInstaller packaging/cellsmith.spec --clean --noconfirm
IF ERRORLEVEL 1 goto :fail

:: Versioned archive
FOR /F "usebackq delims=" %%v IN (`conda run -n CellSmithEnv python -c "ns={}; exec(open('src/__version__.py').read(), ns); print(ns['__version__'])"`) DO SET VERSION=%%v
IF "%VERSION%"=="" goto :fail
:: Robust archiver (retries on the transient AV file-lock; fails LOUD so the
:: ERRORLEVEL check below actually fires - the old Compress-Archive one-liner
:: only raised a NON-terminating error and still exited 0).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\make_zip.ps1" -Source "dist\CellSmith" -Dest "dist\CellSmith-v%VERSION%-win64.zip"
IF ERRORLEVEL 1 goto :fail
echo Built dist\CellSmith-v%VERSION%-win64.zip

:: Windows installer (per-user default, admin optional) - built ALONGSIDE the
:: zip when Inno Setup 6 is available; skipped with a warning otherwise.
:: ISCC discovery. An ALREADY-SET %ISCC% wins, so a caller (CI) that has located
:: ISCC itself can pass it in rather than relying on this probe list matching the
:: machine - the GitHub windows-latest image ships Inno Setup 6 but its manifest
:: does not document the install path.
IF NOT "%ISCC%"=="" echo Using ISCC from the environment: %ISCC%
IF "%ISCC%"=="" (
    where iscc >nul 2>nul
    IF NOT ERRORLEVEL 1 set "ISCC=iscc"
)
IF "%ISCC%"=="" IF EXIST "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
IF "%ISCC%"=="" IF EXIST "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
IF "%ISCC%"=="" IF EXIST "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
IF "%ISCC%"=="" (
    echo WARNING: Inno Setup 6 not found - skipping the installer.
    echo          Install it with:  winget install JRSoftware.InnoSetup
) ELSE (
    "%ISCC%" /Qp "/DAppVersion=%VERSION%" "%~dp0packaging\cellsmith.iss"
    IF ERRORLEVEL 1 goto :fail
    echo Built dist\CellSmith-v%VERSION%-setup.exe
)

IF "%~1"=="" pause
exit /b 0

:fail
echo Build FAILED
IF "%~1"=="" pause
exit /b 1
