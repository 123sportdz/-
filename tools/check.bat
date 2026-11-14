@echo off
REM بوابة ما قبل الدفع على ويندوز: نفس ما يفعله CI.
cd /d "%~dp0.."
python -m ruff check . || exit /b 1
python -m pytest -q --ignore=tests/test_dashboard_browser.py %*
