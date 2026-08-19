@echo off
setlocal EnableExtensions

rem CCM Data Intelligence v0.57 - logged command-line scan
set "ROOT=%~dp0"
set "ENV_NAME=%CCM_ENV_NAME%"
if not defined ENV_NAME set "ENV_NAME=ccm_tool"

if "%~1"=="" goto :usage
set "DATA_ROOT=%~f1"
if not exist "%DATA_ROOT%\" (
    echo ERROR: Data root not found: %DATA_ROOT%
    exit /b 2
)

if "%~2"=="" (
    set "OUT_DIR=%~dp1CCM_Scan_Output"
) else (
    set "OUT_DIR=%~f2"
)
set "AOI_PATH=%~3"

where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda was not found. Run this file from Anaconda Prompt.
    exit /b 3
)

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"
if not exist "%OUT_DIR%\" (
    echo ERROR: Output folder could not be created: %OUT_DIR%
    exit /b 4
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
if not defined STAMP set "STAMP=unknown_time"
set "LOG_FILE=%OUT_DIR%\CCM_Data_Scan_%STAMP%.log"

echo [CCM v0.57] Scanning: %DATA_ROOT%
echo Output: %OUT_DIR%
echo Log: %LOG_FILE%

if "%AOI_PATH%"=="" (
    call conda run -n "%ENV_NAME%" python -B "%ROOT%ccm_step0b_intelligence.py" --data-root "%DATA_ROOT%" --out "%OUT_DIR%" > "%LOG_FILE%" 2>&1
) else (
    if not exist "%AOI_PATH%" (
        echo ERROR: AOI not found: %AOI_PATH%
        exit /b 5
    )
    call conda run -n "%ENV_NAME%" python -B "%ROOT%ccm_step0b_intelligence.py" --data-root "%DATA_ROOT%" --aoi "%AOI_PATH%" --out "%OUT_DIR%" > "%LOG_FILE%" 2>&1
)
set "RC=%ERRORLEVEL%"

echo.
type "%LOG_FILE%"
echo.
if not "%RC%"=="0" (
    echo SCAN FAILED with exit code %RC%.
) else (
    echo SCAN COMPLETED. Review the factual report before selecting Step 1 inputs.
)
exit /b %RC%

:usage
echo Usage:
echo   RUN_DATA_SCAN.bat "DATA_ROOT" ["OUTPUT_FOLDER"] ["AOI_PATH"]
echo.
echo Example:
echo   RUN_DATA_SCAN.bat "D:\GIS\Data" "D:\GIS\Project" "D:\GIS\Data\Extent\AOI.shp"
exit /b 1
