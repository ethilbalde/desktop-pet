@echo off
rem Construit AraigneeBureau.exe (un seul fichier, sans Python requis pour l'utilisateur).
rem Prerequis sur ta machine : Python + "pip install pyinstaller"
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name AraigneeBureau --exclude-module PIL araignee.py
echo.
echo Termine : dist\AraigneeBureau.exe
pause
