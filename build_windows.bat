@echo off
REM ===========================================================================
REM  Build Paragon Publisher into a standalone Windows .exe (no console window)
REM
REM  Just double-click this file, or run it from a command prompt. When it
REM  finishes you'll find the program at:  dist\Paragon Publisher.exe
REM ===========================================================================
setlocal

echo.
echo === [1/3] Installing dependencies + PyInstaller ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo.
echo === [2/3] Building the executable (this can take a few minutes) ===
REM  --windowed          : GUI app, no background console window
REM  --onefile           : produce a single self-contained .exe
REM  --collect-all X     : bundle data files / binaries these packages load at
REM                        runtime (themes, the tkdnd drag-drop binaries, etc.)
REM  To add an icon, drop an .ico beside this file and add:  --icon app.ico
pyinstaller --noconfirm --clean ^
  --name "Paragon Publisher" ^
  --windowed ^
  --onefile ^
  --collect-all customtkinter ^
  --collect-all tkinterdnd2 ^
  --collect-all PIL ^
  paragon_publisher.py
if errorlevel 1 goto :error

echo.
echo === [3/3] Done ===
echo Your program is here:  dist\Paragon Publisher.exe
echo.
echo NOTE: "Stream Details" (codec/resolution/audio info) needs ffprobe on your
echo       PATH. Install ffmpeg (https://ffmpeg.org) if you want that feature.
echo.
pause
exit /b 0

:error
echo.
echo *** Build failed. See the messages above. ***
pause
exit /b 1
