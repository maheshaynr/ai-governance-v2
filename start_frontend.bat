@echo off
REM ============================================================
REM  Start the AI Governance frontend (Vite dev server)
REM  Serves on http://localhost:5173
REM ============================================================

cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo node_modules not found - running npm install first...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
)

echo Starting frontend dev server ...
echo The backend must be running on the port set in frontend\.env (VITE_API_BASE) for the UI to work.
echo.

call npm run dev

echo.
echo Frontend stopped.
pause
