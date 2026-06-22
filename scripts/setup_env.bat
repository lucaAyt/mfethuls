@echo off
echo === mfethuls First-Run Setup ===
echo.
echo Please enter the paths below. These will be saved to .env in this folder.
echo.

set /p DATA_PATH="Path to raw instrument data folder: "
if "%DATA_PATH%"=="" (
    echo PATH_TO_DATA is required.
    exit /b 1
)

set /p REGISTRY_PATH="Path to registry CSV file: "
if "%REGISTRY_PATH%"=="" (
    echo PATH_TO_REGISTRY is required.
    exit /b 1
)

set /p STORAGE_PATH="Path for processed storage (leave blank for .\mfethuls_storage): "
if "%STORAGE_PATH%"=="" set "STORAGE_PATH=.\mfethuls_storage"

(
    echo PATH_TO_DATA=%DATA_PATH%
    echo PATH_TO_REGISTRY=%REGISTRY_PATH%
    echo PATH_TO_LOCAL_STORAGE=%STORAGE_PATH%
) > .env

echo.
echo Configuration saved to .env
