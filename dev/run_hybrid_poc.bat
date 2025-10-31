@echo off
REM Hybrid Backend POC Runner for Windows

echo.
echo ========================================
echo   Hybrid Backend POC
echo ========================================
echo.

if "%~1"=="" (
    echo Usage: run_hybrid_poc.bat "Your prompt here"
    echo.
    echo Example:
    echo   run_hybrid_poc.bat "Explain quantum computing in simple terms"
    echo.
    exit /b 1
)

python dev/hybrid_backend_poc.py %*
