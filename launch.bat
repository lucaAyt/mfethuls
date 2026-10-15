@echo off
cd /d "%~dp0"

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo uv is not installed or not on PATH.
    echo Install it from: https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

echo Starting mfethuls Explorer...
uv run --extra viz --extra notebook mfethuls-app
