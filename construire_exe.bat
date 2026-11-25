@echo off
rem Construit DesktopPet.exe (un seul fichier, sans Python requis pour l'utilisateur).
rem Prerequis sur ta machine : Python + "pip install pyinstaller pillow"
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name DesktopPet --exclude-module numpy --exclude-module PIL.ImageQt --exclude-module PIL.ImageTk --exclude-module unittest --exclude-module pydoc --exclude-module doctest araignee.py
echo.
echo Termine : dist\DesktopPet.exe
pause
