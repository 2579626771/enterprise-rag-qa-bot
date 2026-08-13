@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   Enterprise RAG Frontend starting...
echo   Local:   http://localhost:5173
echo   Network: http://^<your-LAN-IP^>:5173  (for other devices)
echo   Press Ctrl+C to stop
echo ============================================
call npm run dev
pause
