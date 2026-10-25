@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\native-control.ps1" -Action Backup
pause
