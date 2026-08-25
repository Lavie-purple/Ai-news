@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
echo [%date% %time%] run start >> logs\run.log
python main.py --once >> logs\run.log 2>&1
echo [%date% %time%] run end >> logs\run.log
