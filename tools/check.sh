#!/usr/bin/env bash
# بوابة ما قبل الدفع: نفس ما يفعله CI محلياً.
#   ./tools/check.sh          فحص + اختبارات
#   ./tools/check.sh --cov    مع تقرير تغطية (يحتاج pytest-cov)
set -euo pipefail
cd "$(dirname "$0")/.."

python -m ruff check .

if [ "${1:-}" = "--cov" ]; then
  shift
  python -m pytest -q --ignore=tests/test_dashboard_browser.py \
    --cov=reelkit --cov=dashboard --cov-report=term-missing "$@"
else
  python -m pytest -q --ignore=tests/test_dashboard_browser.py "$@"
fi
