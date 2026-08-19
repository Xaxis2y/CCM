@echo off
setlocal EnableExtensions

rem CCM Data Intelligence v0.58.2 - standalone GUI launcher
set "ROOT=%~dp0"
set "ENV_NAME=%CCM_ENV_NAME%"
if not defined ENV_NAME set "ENV_NAME=ccm_tool"

where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda was not found. Run this file from Anaconda Prompt.
    exit /b 2
)

call conda run -n "%ENV_NAME%" python "%ROOT%CCM_Data_Scanner_GUI.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo ERROR: The scanner GUI exited with code %RC%.
    echo Run CCM_anaconda.bat, then try again.
)
exit /b %RC%
