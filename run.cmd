@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "FET_LAUNCHED=0"
where python >nul 2>nul && python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>nul && (
  set "FET_LAUNCHED=1"
  python run.py %*
)
if "%FET_LAUNCHED%"=="0" where py >nul 2>nul && py -3.14 -c "import sys" >nul 2>nul && (set "FET_LAUNCHED=1" & py -3.14 run.py %*)
if "%FET_LAUNCHED%"=="0" where py >nul 2>nul && py -3.13 -c "import sys" >nul 2>nul && (set "FET_LAUNCHED=1" & py -3.13 run.py %*)
if "%FET_LAUNCHED%"=="0" where py >nul 2>nul && py -3.12 -c "import sys" >nul 2>nul && (set "FET_LAUNCHED=1" & py -3.12 run.py %*)
if "%FET_LAUNCHED%"=="0" where py >nul 2>nul && py -3.11 -c "import sys" >nul 2>nul && (set "FET_LAUNCHED=1" & py -3.11 run.py %*)
if "%FET_LAUNCHED%"=="0" where py >nul 2>nul && py -3.10 -c "import sys" >nul 2>nul && (set "FET_LAUNCHED=1" & py -3.10 run.py %*)
if "%FET_LAUNCHED%"=="0" (
  echo No compatible Python interpreter was found.
  echo Checked python and py launcher versions 3.14, 3.13, 3.12, 3.11 and 3.10.
  echo Install 64-bit Python 3.10 or newer, or use the portable Windows package.
  set "FET_EXIT=1"
) else (
  set "FET_EXIT=%ERRORLEVEL%"
)
popd
if not "%FET_EXIT%"=="0" (
  echo.
  echo FET Analyzer could not complete. Read the error above.
  echo Source launch requires Python 3.10 or newer. For no-Python use the portable package.
  pause
)
exit /b %FET_EXIT%
