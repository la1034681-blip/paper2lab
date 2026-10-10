@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Paper2Lab 启动器
set PORT=8501
set PY=%~dp0.venv\Scripts\python.exe

if not exist "%PY%" (
  echo [错误] 未找到虚拟环境 .venv
  echo        请先执行:  python -m venv .venv
  echo                  .venv\Scripts\pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo 服务已在运行, 直接打开浏览器...
  start "" http://127.0.0.1:%PORT%
  timeout /t 3 >NUL
  exit /b 0
)

echo ============================================================
echo   Paper2Lab 启动中, 端口 %PORT%
echo   会弹出一个标题为「Paper2Lab 服务窗口」的窗口 - 请不要关闭它
echo   服务就绪后会自动打开浏览器(约 10 秒)
echo ============================================================
echo.

start "Paper2Lab 服务窗口-关闭即停止服务" "%PY%" -m streamlit run "%~dp0app.py" --server.port %PORT% --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false

echo 等待服务就绪...
set /a n=0
:wait
set /a n+=1
curl -s -o NUL http://127.0.0.1:%PORT%/_stcore/health
if not errorlevel 1 goto ready
if %n% geq 120 goto timeout
timeout /t 1 >NUL
goto wait

:ready
echo 服务已就绪, 正在打开浏览器: http://127.0.0.1:%PORT%
start "" http://127.0.0.1:%PORT%
echo.
echo 提示: 本窗口可以关闭; 停止服务请关闭「Paper2Lab 服务窗口」或双击 停止网页.bat
timeout /t 6 >NUL
exit /b 0

:timeout
echo [错误] 服务启动超时, 请查看「Paper2Lab 服务窗口」里的报错信息。
pause
exit /b 1
