@echo off
REM ============================================================
REM  Start the AI Governance backend (FastAPI / uvicorn)
REM  Bound to 0.0.0.0 so other devices on the LAN (e.g. a phone
REM  running VOXA) can reach it via this machine's own IP --
REM  reachable at http://<this-machine's-LAN-IP>:8000, not just
REM  127.0.0.1. Requires a Windows Firewall inbound rule for TCP
REM  8000 -- see README/CLAUDE notes if devices still can't connect.
REM  Roles are self-declared via the X-Role header (see auth.py) -- there is no
REM  login or secret, so anything on the same network segment can declare
REM  whichever role it wants. require_role() still enforces per-endpoint bands,
REM  but that is a workflow distinction, not a security boundary.
REM ============================================================

cd /d "%~dp0"


if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo         Create it and install requirements.txt first.
    pause
    exit /b 1
)

echo Starting backend on http://0.0.0.0:8000 (reachable via this machine's LAN IP) ...
echo First startup is slow - Presidio, SpaCy, Detoxify and the RAG engine
echo all load into memory. Wait for "Application startup complete."
echo.

".venv\Scripts\python.exe" -m uvicorn api:app --host 0.0.0.0 --port 8000

echo.
echo Backend stopped.
pause
