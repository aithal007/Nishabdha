@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
set PYTHONUTF8=1
python -m pytest -q
set TEST_VOICE=local
python -m pytest -q tests\test_real_models.py
