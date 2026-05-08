@echo off
cd /d D:\BFA-Scout

echo Starting Flask...
start "" /MIN "D:\BFA-Scout\.venv\Scripts\flask.exe" --app wsgi run

echo Waiting for Flask to start...
timeout /t 5 /nobreak > nul

echo === BFA-Scout Verification === > _verify_output.txt
echo. >> _verify_output.txt

echo [1] /health >> _verify_output.txt
curl -s http://localhost:5000/health >> _verify_output.txt
echo. >> _verify_output.txt

echo [2] / (checking for "BFA Scouting") >> _verify_output.txt
curl -s http://localhost:5000/ | findstr "BFA Scouting" >> _verify_output.txt
echo. >> _verify_output.txt

echo [3] /auth/ >> _verify_output.txt
curl -s http://localhost:5000/auth/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [4] /players/ >> _verify_output.txt
curl -s http://localhost:5000/players/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [5] /evaluations/ >> _verify_output.txt
curl -s http://localhost:5000/evaluations/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [6] /criteria/ >> _verify_output.txt
curl -s http://localhost:5000/criteria/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [7] /wyscout/ >> _verify_output.txt
curl -s http://localhost:5000/wyscout/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [8] /reports/ >> _verify_output.txt
curl -s http://localhost:5000/reports/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [9] /ai/ >> _verify_output.txt
curl -s http://localhost:5000/ai/ >> _verify_output.txt
echo. >> _verify_output.txt

echo [10] /api/ >> _verify_output.txt
curl -s http://localhost:5000/api/ >> _verify_output.txt
echo. >> _verify_output.txt

echo Stopping Flask...
taskkill /f /im flask.exe > nul 2>&1
taskkill /f /im python.exe /fi "WINDOWTITLE eq flask*" > nul 2>&1

notepad _verify_output.txt
