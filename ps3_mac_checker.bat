@echo off
setlocal
title PS3 Controller MAC Address Checker

:: Check if Python is available in PATH
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PY_CMD=py -3"
    ) else (
        echo [!] Python is not installed or not in your system PATH.
        echo Please install Python 3.10+ from https://www.python.org/
        echo Make sure to check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
)

"%PY_CMD%" "%~dp0ps3_mac_checker.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% NEQ 0 (
    echo.
    echo [!] Program exited with error code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
