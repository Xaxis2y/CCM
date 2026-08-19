@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem CCM Tool v0.57 - dedicated standalone Anaconda environment
rem Usage: CCM_anaconda.bat [environment_name] [--with-gdal]
set "ENV_NAME=ccm_tool"
set "INSTALL_GDAL=0"

:parse_args
if "%~1"=="" goto :parsed_args
if /I "%~1"=="--with-gdal" (
    set "INSTALL_GDAL=1"
) else if /I "%~1"=="--help" (
    goto :usage
) else (
    set "ENV_NAME=%~1"
)
shift
goto :parse_args

:parsed_args
where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda was not found. Run this file from Anaconda Prompt.
    exit /b 2
)

echo [CCM v0.57] Preparing dedicated environment: %ENV_NAME%
call conda run -n "%ENV_NAME%" python --version >nul 2>&1
if errorlevel 1 (
    echo Creating environment with Python 3.11 and pip...
    call conda create -n "%ENV_NAME%" python=3.11 pip -y
    if errorlevel 1 (
        echo ERROR: conda could not create %ENV_NAME%.
        exit /b 3
    )
) else (
    echo Environment already exists; refreshing CCM verification tools.
)

echo Installing pytest, pyflakes, and PyInstaller...
call conda run -n "%ENV_NAME%" python -m pip install --upgrade pip pytest pyflakes pyinstaller
if errorlevel 1 (
    echo ERROR: required CCM tools could not be installed.
    exit /b 4
)

if "%INSTALL_GDAL%"=="1" (
    echo Installing optional GDAL/OGR support from conda-forge...
    call conda install -n "%ENV_NAME%" -c conda-forge gdal -y
    if errorlevel 1 (
        echo ERROR: optional GDAL installation failed.
        exit /b 5
    )
)

echo.
echo CCM Anaconda environment is ready: %ENV_NAME%
call conda run -n "%ENV_NAME%" python -c "import sys, pytest, pyflakes; print('Python', sys.version.split()[0]); print('pytest', pytest.__version__); print('pyflakes', pyflakes.__version__)"
echo.
echo To use it in this prompt:
echo   conda activate %ENV_NAME%
echo.
echo This environment supports the standalone scanner, tests, and packaging.
echo ArcPy is licensed ArcGIS Pro software and is intentionally not installed here.
echo Use RUN_ARCGIS_SMOKE_TEST.bat for the ArcPy/GDB smoke test.
echo Next verification command: RUN_V057_TESTS.bat
exit /b 0

:usage
echo Usage:
echo   CCM_anaconda.bat [environment_name] [--with-gdal]
echo.
echo Examples:
echo   CCM_anaconda.bat
echo   CCM_anaconda.bat ccm_tool_gdal --with-gdal
exit /b 0
