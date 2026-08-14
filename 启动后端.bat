@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   Enterprise RAG 后端启动中...
echo   地址: http://127.0.0.1:8000
echo   文档: http://127.0.0.1:8000/docs
echo   按 Ctrl+C 停止
echo ============================================
rem 内网代理绕行：部分企业系统代理会拦截阿里云/DeepSeek 的公网 HTTPS，
rem 导致 embedding 407 代理认证失败、问答直接挂。这里让这两个域名及本机直连、绕过代理。
rem 若你的环境无需代理，这几行留着也无害。
set NO_PROXY=dashscope.aliyuncs.com,api.deepseek.com,127.0.0.1,localhost
set no_proxy=dashscope.aliyuncs.com,api.deepseek.com,127.0.0.1,localhost
call .venv\Scripts\activate.bat
uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload
pause
