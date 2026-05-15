@echo off
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "D:\BFA-Scout\_verify_phase3.ps1" > "D:\BFA-Scout\_verify_phase3_output.txt" 2>&1
echo Verification complete. See _verify_phase3_output.txt for results.
pause
