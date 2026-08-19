@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem CCM Tool v0.58.2 - licensed ArcGIS/ArcPy smoke tests (all 6)
rem
rem v0.58.2 post-review "H-4": this launcher used to run only
rem   tests\arcpy_smoke_test_step0b.py
rem which, due to a file-naming collision fixed in the same pass, was
rem ALWAYS the Step 0b Data Intelligence test -- never the Step 2 mobility
rem engine test (previously tests\arcpy_smoke_test.py, renamed to
rem tests\arcpy_smoke_test_step2.py). The only licensed ArcGIS launcher in
rem the project therefore never exercised Step 2 -- the tool's core output,
rem and the exact code path where ERROR 000384 was found in v0.54.4. See
rem CHANGELOG_v0.58.2.md "H-4".
rem
rem This script now runs all six ArcPy smoke tests (step0, step1, step2,
rem step3, factual step0b, integrated step0b) and reports a combined PASS/FAIL. It also locates
rem propy.bat instead of assuming the default install path, since that
rem literal path fails on a per-user or non-C: ArcGIS Pro install.

set "ROOT=%~dp0"

rem ── Locate propy.bat ─────────────────────────────────────────────────────
set "PROPY="
for %%P in (
    "%ProgramFiles%\ArcGIS\Pro\bin\Python\Scripts\propy.bat"
    "%ProgramFiles(x86)%\ArcGIS\Pro\bin\Python\Scripts\propy.bat"
    "%LOCALAPPDATA%\Programs\ArcGIS\Pro\bin\Python\Scripts\propy.bat"
) do (
    if not defined PROPY if exist %%P set "PROPY=%%~P"
)
if not defined PROPY (
    for /f "tokens=2,*" %%A in (
        'reg query "HKLM\SOFTWARE\ESRI\ArcGISPro" /v InstallDir 2^>nul ^| find "InstallDir"'
    ) do (
        if exist "%%B\bin\Python\Scripts\propy.bat" set "PROPY=%%B\bin\Python\Scripts\propy.bat"
    )
)
if not defined PROPY (
    echo ERROR: ArcGIS Pro propy.bat was not found in any known location.
    echo   Checked: %%ProgramFiles%%\ArcGIS\Pro\bin\Python\Scripts\propy.bat
    echo            %%ProgramFiles(x86)%%\ArcGIS\Pro\bin\Python\Scripts\propy.bat
    echo            %%LOCALAPPDATA%%\Programs\ArcGIS\Pro\bin\Python\Scripts\propy.bat
    echo            HKLM\SOFTWARE\ESRI\ArcGISPro  (InstallDir)
    echo   If ArcGIS Pro is installed somewhere else, set PROPY manually and
    echo   re-run, e.g.:
    echo     set "PROPY=D:\Esri\ArcGIS\Pro\bin\Python\Scripts\propy.bat"
    echo     RUN_ARCGIS_SMOKE_TEST.bat
    exit /b 2
)
echo [CCM v0.58.2] Using propy.bat: %PROPY%

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
if not defined STAMP set "STAMP=unknown_time"
set "LOG_DIR=%ROOT%verification_logs"
set "ART_DIR=%ROOT%verification_artifacts\%STAMP%_arcpy"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%ART_DIR%" mkdir "%ART_DIR%"

set "FAILED="
set "PASSED="

rem ── Step 0 / Step 1 / Step 2 / Step 3: no CLI arguments ─────────────────
for %%T in (step0 step1 step2 step3) do (
    echo.
    echo [CCM v0.58.2] ArcPy smoke test: %%T ────────────────────────────────
    set "LOG_FILE=%LOG_DIR%\%STAMP%_arcpy_%%T.log"
    call "%PROPY%" "%ROOT%tests\arcpy_smoke_test_%%T.py" > "!LOG_FILE!" 2>&1
    set "RC=!ERRORLEVEL!"
    type "!LOG_FILE!"
    if not "!RC!"=="0" (
        echo   %%T FAILED  ^(exit !RC!^) - log: !LOG_FILE!
        set "FAILED=!FAILED! %%T"
    ) else (
        echo   %%T PASSED
        set "PASSED=!PASSED! %%T"
    )
)

rem ── Step 0b: takes --artifact-dir ────────────────────────────────────────
echo.
echo [CCM v0.58.2] ArcPy smoke test: step0b ─────────────────────────────
set "LOG_FILE=%LOG_DIR%\%STAMP%_arcpy_step0b.log"
call "%PROPY%" "%ROOT%tests\arcpy_smoke_test_step0b.py" --artifact-dir "%ART_DIR%" > "%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG_FILE%"
if not "%RC%"=="0" (
    echo   step0b FAILED  ^(exit %RC%^) - log: %LOG_FILE%
    set "FAILED=!FAILED! step0b"
) else (
    echo   step0b PASSED
    set "PASSED=!PASSED! step0b"
)

rem ── v0.58.2 integrated Step 0b: catalog + scoring + recommendations ────
echo.
echo [CCM v0.58.2] ArcPy smoke test: step0b_integrated ───────────────────
set "LOG_FILE=%LOG_DIR%\%STAMP%_arcpy_step0b_integrated.log"
call "%PROPY%" "%ROOT%tests\arcpy_smoke_test_v0582.py" --artifact-dir "%ART_DIR%\integrated" > "%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG_FILE%"
if not "%RC%"=="0" (
    echo   step0b_integrated FAILED  ^(exit %RC%^) - log: %LOG_FILE%
    set "FAILED=!FAILED! step0b_integrated"
) else (
    echo   step0b_integrated PASSED
    set "PASSED=!PASSED! step0b_integrated"
)

echo.
echo ============================================================
if defined FAILED (
    echo ARCPY SMOKE TESTS: FAILED:!FAILED!
    if defined PASSED echo                     passed:!PASSED!
    echo Logs: %LOG_DIR%
    echo Open and sign in to ArcGIS Pro, then rerun this script.
    exit /b 1
)
echo ALL ARCPY SMOKE TESTS PASSED:!PASSED!
echo Logs: %LOG_DIR%
exit /b 0
