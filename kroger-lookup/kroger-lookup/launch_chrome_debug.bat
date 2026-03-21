@echo off
echo ============================================
echo  Kroger Lookup - Chrome Debug Launcher
echo ============================================
echo.
echo This will close ALL Chrome windows, then relaunch
echo Chrome with the debug port enabled (9333).
echo.
echo After Chrome opens:
echo   1. Log into kroger.com
echo   2. Select your store (Pickup/Delivery)
echo   3. Go back to the Kroger Lookup app and click
echo      "Connect to Chrome & Extract Session"
echo.
pause

echo.
echo === Killing all Chrome processes ===
taskkill /F /IM chrome.exe /T >nul 2>&1
taskkill /F /IM GoogleCrashHandler.exe /T >nul 2>&1
taskkill /F /IM GoogleCrashHandler64.exe /T >nul 2>&1
timeout /t 4 /nobreak >nul
echo Chrome closed.

echo.
echo Launching Chrome with debug port 9333...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9333 --remote-allow-origins=* --user-data-dir="%TEMP%\chrome-kroger-debug" https://www.kroger.com
timeout /t 5 /nobreak >nul

netstat -an | find "9333" | find "LISTENING" >nul
if errorlevel 1 (
    echo.
    echo WARNING: Port 9333 not open yet - give Chrome a few more seconds.
) else (
    echo.
    echo SUCCESS: Port 9333 is listening.
    echo Chrome is ready - go to the Kroger Lookup app and click Connect.
)
echo.
echo Keep this window and Chrome open while using the app.
pause
