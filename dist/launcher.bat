@echo off
cls
title CommandMate.exe Launcher
echo Launching CommandMate.exe...
echo =====================
CommandMate.exe
echo =====================
echo.
echo Program finished. Choose an option:
echo [1] Relaunch the program
echo [2] Close this window
echo.
set /p choice=Enter your choice (1-2): 

if "%choice%"=="1" (
    cls
    echo Relaunching CommandMate.exe...
    echo =====================
    CommandMate.exe
    pause
    exit
) else if "%choice%"=="2" (
    echo Closing...
    exit
) else (
    echo Invalid choice. Closing...
    pause
)
