@echo off
echo Stopping any existing Flask process on port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000"') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 2 /nobreak >nul

echo Starting Flask in debug mode...
cd /d D:\BFA-Scout
call .venv\Scripts\activate
set FLASK_APP=wsgi
set FLASK_ENV=development
start "BFA-Scout Flask" cmd /k ".venv\Scripts\flask --app wsgi run --debug"
echo Flask started. Waiting 4 seconds for startup...
timeout /t 4 /nobreak >nul
echo Done. Flask should be running at http://127.0.0.1:5000
pause
