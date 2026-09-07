@echo off
setlocal
pushd "%~dp0" || exit /b 1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py %*
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 run.py %*
  ) else (
    python run.py %*
  )
)
set "FET_EXIT=%ERRORLEVEL%"
popd
if not "%FET_EXIT%"=="0" (
  echo.
  echo FET Analyzer could not complete. Read the error above.
  echo Source launch requires Python 3.11-3.13. For no-Python use the portable package.
  pause
)
exit /b %FET_EXIT%
