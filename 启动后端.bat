@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   Enterprise RAG 后端启动中...
echo   地址: http://127.0.0.1:8000
echo   文档: http://127.0.0.1:8000/docs
echo   按 Ctrl+C 停止
echo ============================================
call .venv\Scripts\activate.bat
uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload
pause
