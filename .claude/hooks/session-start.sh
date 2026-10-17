#!/bin/bash
# Claude Code 웹(원격) 세션 시작 시 의존성 설치 — 새 세션이 바로 테스트·CLI·웹 서버를 돌릴 수 있게 한다.
set -euo pipefail
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
pip install -q -e ".[dev,web]" 2>&1 | grep -v "Running pip as the 'root' user" || true
