@echo off
setlocal
cd /d "%~dp0"

set "PYW=%cd%\.venv\Scripts\pythonw.exe"
set "PY=%cd%\.venv\Scripts\python.exe"
set "RUN=%cd%\run.py"

set "EVA_LAUNCHER=1"
if exist "%PYW%" (
  start "Eva" /D "%cd%" "%PYW%" "%RUN%" --gui %*
  exit /b 0
)
if exist "%PY%" (
  start "Eva" /D "%cd%" "%PY%" "%RUN%" --gui %*
  exit /b 0
)

echo [.venv] not found.
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
pause
exit /b 1
