@echo off
setlocal EnableExtensions
title PS3 Controller MAC Address Manager
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"

set "PY_EXE="
set "PY_ARGS="
call :detect_python
if defined PY_EXE goto :run_manager

echo [!] Python 3.8+ is not installed or not in your system PATH.
where winget >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo.
    set /p "INSTALL_PY=Install Python 3 automatically via winget? [Y/n]: "
    if /i "%INSTALL_PY%"=="" set "INSTALL_PY=Y"
    if /i "%INSTALL_PY%"=="Y" (
        echo [*] Installing Python 3.12 via winget...
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        call :detect_python
        if defined PY_EXE goto :run_manager
        echo.
        echo [i] Python installation finished. Please close this window and double-click ps3_mac_manager.bat again.
        pause
        exit /b 1
    )
)

echo.
echo Please install Python 3.10+ from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:run_manager
if defined PY_ARGS (
    "%PY_EXE%" %PY_ARGS% "%~dp0ps3_mac_manager.py" %*
) else (
    "%PY_EXE%" "%~dp0ps3_mac_manager.py" %*
)
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% NEQ 0 (
    echo %* | findstr /i /c:"--non-interactive" /c:"-n" /c:"--json" /c:"-j" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [!] Program exited with error code %EXIT_CODE%.
        pause
    )
)

exit /b %EXIT_CODE%

:detect_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
    exit /b 0
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY_EXE=python"
    exit /b 0
)

python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY_EXE=python3"
    exit /b 0
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
        if not errorlevel 1 (
            set "PY_EXE=%%~fD\python.exe"
            exit /b 0
        )
    )
)
exit /b 1
