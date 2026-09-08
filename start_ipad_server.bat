@echo off
setlocal
cd /d "%~dp0"
title Space Idle v0.4.4 - iPad Server
echo ============================================================
echo  Space Idle v0.4.4 - iPad LAN development server
echo ============================================================
echo.
echo PC LAN IPv4 candidates:
ipconfig | findstr /R /C:"IPv4"
echo.
echo Start URL: http://^<PC-LAN-IPv4^>:8765/
echo Keep this window open while using the iPad.
echo Windows Firewall may ask for permission on the first launch.
echo.
py -m space_idle.api --host 0.0.0.0 --port 8765 --save-dir saves
if errorlevel 1 (
  echo.
  echo Python launcher "py" failed. Trying "python"...
  python -m space_idle.api --host 0.0.0.0 --port 8765 --save-dir saves
)
pause
