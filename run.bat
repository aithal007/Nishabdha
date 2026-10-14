@echo off
cd /d %~dp0
if not exist .venv\Scripts\activate.bat (
  echo Run setup.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
set PYTHONUTF8=1
REM Models are already downloaded: don't re-check huggingface.co on every start (venue Wi-Fi is slow).
if exist models\ecapa\embedding_model.ckpt (
  set HF_HUB_OFFLINE=1
  set TRANSFORMERS_OFFLINE=1
)
echo Starting UNCLONE on http://localhost:8000  (log: server.log)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath server.log"
pause
