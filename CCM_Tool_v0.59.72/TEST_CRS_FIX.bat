@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================
rem  TEST_CRS_FIX.bat
rem  One-shot local verification for the CRS-coverage fix in
rem  ccm_data_catalog.py (reproject_extent(), coverage_pct(),
rem  _polygon_intersection_pct_arcpy/_ogr, build_record()).
rem
rem  Run this from Anaconda Prompt, inside this CCM_Tool_v0.59.6
rem  folder. It does NOT bump the version or rename any files --
rem  it only runs this project's own existing verification
rem  scripts (CCM_anaconda.bat / RUN_TESTS.bat /
rem  RUN_ARCGIS_SMOKE_TEST.bat) back to back and collects their
rem  results in one summary. Safe to re-run any number of times.
rem ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
if not defined STAMP set "STAMP=unknown_time"
if not exist "%ROOT%verification_logs" mkdir "%ROOT%verification_logs"
set "SUMMARY=%ROOT%verification_logs\%STAMP%_TEST_CRS_FIX_summary.txt"

echo ============================================================ > "%SUMMARY%"
echo  CCM CRS-coverage fix verification -- %STAMP% >> "%SUMMARY%"
echo ============================================================ >> "%SUMMARY%"

where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda was not found. Run this file from Anaconda Prompt.
    echo ERROR: conda not found on PATH >> "%SUMMARY%"
    type "%SUMMARY%"
    exit /b 2
)

rem ---- Step 1: dedicated env must exist ----------------------------------
echo.
echo [1/3] Checking dedicated environment "ccm_tool" ...
call conda run -n ccm_tool python --version >nul 2>&1
if errorlevel 1 (
    echo   Not found yet -- creating/preparing it now via CCM_anaconda.bat ...
    call "%ROOT%CCM_anaconda.bat"
    if errorlevel 1 (
        echo   ERROR: CCM_anaconda.bat failed -- see its output above.
        echo STEP 1 FAILED: CCM_anaconda.bat >> "%SUMMARY%"
        type "%SUMMARY%"
        exit /b 3
    )
    echo STEP 1 OK: environment created by CCM_anaconda.bat >> "%SUMMARY%"
) else (
    echo   Found. ^(Run CCM_anaconda.bat yourself first if you want it refreshed.^)
    echo STEP 1 OK: environment already present >> "%SUMMARY%"
)

rem ---- Step 2: portable checks (syntax, pyflakes, pytest -- no ArcGIS) ---
echo.
echo [2/3] Portable checks: syntax, pyflakes, pytest, fixture scan ...
echo       (RUN_TESTS.bat -^> package_ccm.py --verify-only)
call "%ROOT%RUN_TESTS.bat"
set "RC2=%ERRORLEVEL%"
if not "%RC2%"=="0" (
    echo   FAILED -- exit code %RC2%. See the log path printed above.
    echo STEP 2 FAILED: RUN_TESTS.bat  exit %RC2% >> "%SUMMARY%"
) else (
    echo   PASSED.
    echo STEP 2 OK: RUN_TESTS.bat >> "%SUMMARY%"
)

rem ---- Step 3: licensed ArcPy smoke tests --------------------------------
echo.
echo [3/3] Licensed ArcPy smoke tests (needs ArcGIS Pro open and signed in) ...
echo       (RUN_ARCGIS_SMOKE_TEST.bat -^> exercises the real .projectAs^(^) path)
call "%ROOT%RUN_ARCGIS_SMOKE_TEST.bat"
set "RC3=%ERRORLEVEL%"
if not "%RC3%"=="0" (
    echo   FAILED -- exit code %RC3%. See the per-test logs printed above.
    echo STEP 3 FAILED: RUN_ARCGIS_SMOKE_TEST.bat  exit %RC3% >> "%SUMMARY%"
) else (
    echo   PASSED.
    echo STEP 3 OK: RUN_ARCGIS_SMOKE_TEST.bat >> "%SUMMARY%"
)

echo.
echo ============================================================
if not "%RC2%"=="0" (
    echo RESULT: FAILED at step 2 ^(portable checks^).
) else if not "%RC3%"=="0" (
    echo RESULT: FAILED at step 3 ^(ArcPy smoke tests^).
) else (
    echo RESULT: ALL CHECKS PASSED.
    echo.
    echo Confirm the fix itself ran by finding this line in the step0b
    echo smoke-test output above:
    echo   PASS: cross-CRS coverage ^(SRTM_30m.tif EPSG:4326 vs AOI EPSG:32636^) computed = ...
)
echo ============================================================
echo RESULT (see above) >> "%SUMMARY%"

echo.
echo Most recent log files in verification_logs\:
set "CNT=0"
for /f "delims=" %%F in ('dir /b /o-d "%ROOT%verification_logs\*.log" 2^>nul') do (
    if !CNT! LSS 6 (
        echo   %%F
        echo   %%F >> "%SUMMARY%"
    )
    set /a CNT+=1
)

echo.
echo Full summary written to:
echo   %SUMMARY%
echo If anything FAILED, send me that summary file plus the newest
echo log(s) listed above with today's timestamp (%STAMP%).
echo.
pause
