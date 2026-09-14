@echo off
REM ============================================================
REM  Start both backend and frontend, each in its own window
REM ============================================================

cd /d "%~dp0"

echo Launching backend window...
start "AI Governance - Backend" cmd /k "%~dp0start_backend.bat"

echo Launching frontend window...
start "AI Governance - Frontend" cmd /k "%~dp0start_frontend.bat"

echo.
echo Both started in separate windows:
echo   Backend  -^> see the backend window for its actual port (start_backend.bat --port)
echo   Frontend -^> http://localhost:5173
echo.
echo Close those windows (or press Ctrl+C in them) to stop the services.
