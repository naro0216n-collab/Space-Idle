@echo off
setlocal
cd /d "%~dp0"
title Space Idle - Update and Start iPad Server

echo ============================================================
echo  Space Idle - Git update and iPad server startup
echo ============================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo ERROR: git was not found in PATH.
  echo Install Git for Windows or add git.exe to PATH, then run this file again.
  echo.
  pause
  exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
  echo ERROR: This folder is not a Git working tree.
  echo Clone the GitHub repository instead of using a ZIP if you want automatic updates.
  echo.
  pause
  exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
if not defined CURRENT_BRANCH (
  echo ERROR: No current Git branch is checked out.
  echo.
  pause
  exit /b 1
)

echo Current branch: %CURRENT_BRANCH%
echo Updating from its configured upstream with fast-forward only...
echo.

git pull --ff-only
if errorlevel 1 (
  echo.
  echo ERROR: Git update failed. The server was not started.
  echo Resolve local changes, branch divergence, authentication, or network issues and retry.
  echo.
  pause
  exit /b 1
)

echo.
echo Update complete. Starting the iPad server...
echo.
call "%~dp0start_ipad_server.bat"
exit /b %errorlevel%
