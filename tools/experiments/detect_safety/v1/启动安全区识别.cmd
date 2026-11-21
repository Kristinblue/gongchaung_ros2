@echo off
chcp 65001 >nul
cd /d "%~dp0"
"D:\MySoftware\miniconda3\envs\yolov8\python.exe" window.py
if errorlevel 1 pause
