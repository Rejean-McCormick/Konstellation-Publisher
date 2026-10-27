@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 Konstellation_Publisher.pyw
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw Konstellation_Publisher.pyw
  exit /b 0
)
py -3 Konstellation_Publisher.pyw
