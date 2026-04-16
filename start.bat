@echo off
setlocal

cd /d "%~dp0"

if not exist ".deps" (
  echo [ERROR] 未找到 .deps 目录，请先运行 install.ps1
  pause
  exit /b 1
)

set "PYTHONPATH=.deps"

echo Starting graduate-review-studio on http://127.0.0.1:8000
uv run --python 3.12 python -m uvicorn app:app --host 127.0.0.1 --port 8000

endlocal
