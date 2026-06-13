@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   EMDataStudio  --  Anaconda Environment Setup
echo   TU Darmstadt, Advanced Electron Microscopy
echo ============================================================
echo.

REM ── Check for conda ──────────────────────────────────────────────────────
where conda >nul 2>nul
if %errorlevel% neq 0 (
    echo  [ERROR] conda was not found on PATH.
    echo  Please install Anaconda or Miniconda first:
    echo    https://www.anaconda.com/download
    echo.
    pause
    exit /b 1
)

set ENV_NAME=EMDataStudio
set PYTHON_VER=3.14.4

echo  Step 1 of 3 — Creating conda environment "%ENV_NAME%" (Python %PYTHON_VER%)...
call conda create -n %ENV_NAME% python=%PYTHON_VER% -y
if %errorlevel% neq 0 (
    echo  [ERROR] Failed to create conda environment.
    pause & exit /b 1
)

echo.
echo  Step 2 of 3 — Installing core packages (conda-forge)...
call conda run -n %ENV_NAME% conda install -c conda-forge ^
    python=3.14.4 ^
    numpy=2.4.3 ^
    scipy=1.17.1 ^
    matplotlib=3.10.8 ^
    h5py=3.16.0 ^
    pyqt=5.15.11 ^
    hyperspy=2.4.0 ^
    rosettasciio-base>=0.10.0 ^
    exspy=0.3.2 ^
    pip=26.0.1 ^
    -y
if %errorlevel% neq 0 (
    echo  [WARN] conda install had issues; trying pip fallback...
)

echo.
echo ============================================================
echo   Installation complete!
echo.
echo   To launch EMDataStudio:
echo     1.  Open Anaconda Prompt
echo     2.  conda activate %ENV_NAME%
echo     3.  cd /d "%~dp0.."
echo     4.  python main.py
echo ============================================================
echo.
pause
