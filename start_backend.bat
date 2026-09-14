@echo off
REM ============================================================
REM  Start the AI Governance backend (FastAPI / uvicorn)
REM  Serves on http://127.0.0.1:8000
REM ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo         Create it and install requirements.txt first.
    pause
    exit /b 1
)

echo Starting backend on http://127.0.0.1:8000 ...
echo First startup is slow - Presidio, SpaCy, Detoxify and the RAG engine
echo all load into memory. Wait for "Application startup complete."
echo.

".venv\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000

echo.
echo Backend stopped.
pause
