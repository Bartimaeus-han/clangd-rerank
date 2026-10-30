#!/usr/bin/env bash
# 체크포인트 하나를 라이브러리 시험셋 5개(eval_ckpt.sh) + 응용 시험셋(eval_app60_sub)으로 평가한다.
# 사용: eval_full.sh <체크포인트> <태그>  → kev_data/compare-<태그>.txt, kev_data/compare-<태그>-app.txt
set -euo pipefail
S="$(cd "$(dirname "$0")/.." && pwd)"
CKPT=$(realpath "$1"); TAG=$2
"$S/clangd_test/eval_ckpt.sh" "$CKPT" "$TAG"
PY="$S/ext/kev/.venv/bin/python"
cd "$S/ext/kev"; export PYTHONPATH=.
pred="$S/kev_data/pred-$TAG-test_app_sub.jsonl"
"$PY" "$S/clangd_test/kev_local_eval.py" "$CKPT" "$S/kev_data/test_app_sub.jsonl" "$pred" >/dev/null 2>"$S/kev_data/pred-$TAG-test_app_sub.log"
"$PY" -I "$S/clangd_test/compare_models.py" "$S/eval_app_sub/samples.jsonl" "$S/kev_data/test_app_sub.jsonl" - "$pred" "$S/eval_app60_sub" | tee "$S/kev_data/compare-$TAG-app.txt"
echo "DONE $TAG"
