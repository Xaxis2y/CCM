@echo off
setlocal EnableExtensions

rem CCM Tool v0.57 - integrated Anaconda verification
set "ROOT=%~dp0"
set "ENV_NAME=%CCM_ENV_NAME%"
if not defined ENV_NAME set "ENV_NAME=ccm_tool"

where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda was not found. Run this file from Anaconda Prompt.
    exit /b 2
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%I"
if not defined STAMP set "STAMP=unknown_time"

set "LOG_DIR=%ROOT%verification_logs"
set "ART_DIR=%ROOT%verification_artifacts\%STAMP%_anaconda"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%ART_DIR%" mkdir "%ART_DIR%"
set "LOG_FILE=%LOG_DIR%\%STAMP%_anaconda_verification.log"

echo [CCM v0.57] Running integrated toolbox and Data Intelligence verification...
echo Log: %LOG_FILE%
echo Artifacts: %ART_DIR%

call conda run -n "%ENV_NAME%" python -B "%ROOT%package_ccm_v057.py" --verify-only --artifact-dir "%ART_DIR%" > "%LOG_FILE%" 2>&1
set "RC=%ERRORLEVEL%"

echo.
type "%LOG_FILE%"
echo.
if not "%RC%"=="0" (
    echo VERIFICATION FAILED with exit code %RC%.
    echo Send this log for review: %LOG_FILE%
) else (
    echo VERIFICATION PASSED.
    echo Log saved: %LOG_FILE%
)
exit /b %RC%
