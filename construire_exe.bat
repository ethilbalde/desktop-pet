@echo off
rem Construit AraigneeBureau.exe (un seul fichier, sans Python requis pour l'utilisateur).
rem Prerequis sur ta machine : Python + "pip install pyinstaller pillow"
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name AraigneeBureau --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module PIL.ImageTk --exclude-module unittest --exclude-module pydoc --exclude-module doctest araignee.py
echo.
echo Termine : dist\AraigneeBureau.exe
pause
