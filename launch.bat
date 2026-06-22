@echo off
cd /d "%~dp0"

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv is not installed or not on PATH.
    echo Install it from: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

if not exist ".env" (
    echo First-time setup: configuring paths...
    echo.
    call scripts\setup_env.bat
    if %errorlevel% neq 0 (
        echo Setup failed. Please try again.
        pause
        exit /b 1
    )
    echo.
)

echo Starting mfethuls Explorer...
uv run --extra viz streamlit run apps/streamlit_app.py
