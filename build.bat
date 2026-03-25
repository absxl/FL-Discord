@echo off
:: ============================================================
::  build.bat — compiles fl_discord_rpc.py into a single .exe
::  Run this once on YOUR machine, then share the .exe
:: ============================================================

echo Installing build tools...
python -m pip install pyinstaller pypresence pystray Pillow pywin32 psutil keyboard --quiet

echo.
echo Building fl_discord_rpc.exe ...
python -m PyInstaller ^
    --onefile ^
    --noconsole ^
    --name "FL Discord RPC" ^
    --collect-all pypresence ^
    fl_discord_rpc.py

echo.
echo Done! Your exe is in the dist\ folder.
echo Share "dist\FL Discord RPC.exe" with your friends.
pause
