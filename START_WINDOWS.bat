@echo off
cd /d "%~dp0"
echo.
echo  UNIBEN Crime Records and Information System
 echo  Running on http://127.0.0.1:8080
 echo  Keep this window open during your demonstration.
echo.
where py >nul 2>&1
if %errorlevel%==0 (
  py server.py
) else (
  python server.py
)
pause
