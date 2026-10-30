#!/usr/bin/env bash
# F 단계: 체크포인트를 2단계(v2 LightGBM)로 거른 상위 K=60/30 후보 세트에서 평가한다 (5개 프로젝트).
# 사용: eval_s2.sh <체크포인트> <태그>  → kev_data/pred-<태그>-s2k{60,30}_<프로젝트>.jsonl
set -euo pipefail
S="$(cd "$(dirname "$0")/.." && pwd)"
CKPT=$(realpath "$1"); TAG=$2
cd "$S/ext/kev"; export PYTHONPATH=.
for K in 60 30; do for n in cli fmt lz4 entt cxxopts; do
  .venv/bin/python "$S/clangd_test/kev_local_eval.py" "$CKPT" "$S/kev_data/s2k${K}_$n.jsonl" "$S/kev_data/pred-$TAG-s2k${K}_$n.jsonl" >/dev/null 2>"$S/kev_data/pred-$TAG-s2k${K}_$n.log"
  echo "done s2k${K}_$n"
done; done
