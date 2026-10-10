@echo off
chcp 65001 >nul
title Paper2Lab 停止服务
echo 正在停止占用 8501 端口的 Paper2Lab 服务...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8501 .*LISTENING"') do (
  echo   kill PID %%p
  taskkill /F /PID %%p >nul 2>&1
)
echo 完成。
timeout /t 3 >NUL
