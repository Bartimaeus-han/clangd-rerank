#!/usr/bin/env bash
# Jev(TypeSafe API) 재정렬 단계만 실행한다. 인자: 평가 디렉터리 이름 (예: eval_bapp)
set -euo pipefail
cd "$(dirname "$0")"
[[ "${1:-}" =~ ^eval_[A-Za-z0-9_]+$ ]] || { echo "사용: run_jev.sh eval_<이름>" >&2; exit 2; }
set -a; . ./jev.env; set +a
# 폴더 이름이 _v2로 끝나면 개선한 지시문(친 글자 명시)을 쓴다
[[ "$1" == *_v2 ]] && export RERANK_PROMPT=v2
jevenv/bin/python -I clangd_test/eval_rerank.py jev "$1" 2>&1 | grep -v "/" || true
jevenv/bin/python -I clangd_test/eval_rerank.py report "$1"
