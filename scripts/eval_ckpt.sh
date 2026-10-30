#!/usr/bin/env bash
# 체크포인트 하나를 CLI11(검증) + 시험셋 4개(fmt, lz4, entt, cxxopts)로 평가하고 비교표를 찍는다.
# 사용: eval_ckpt.sh <체크포인트 경로> <태그>   (예: ext/kev/runs/clangd-0.8b-v2-e1 v2e1)
# 출력: kev_data/pred-<태그>-<셋>.jsonl, 비교표 kev_data/compare-<태그>.txt
set -euo pipefail
S="$(cd "$(dirname "$0")/.." && pwd)"
CKPT=$(realpath "$1"); TAG=$2
PY="$S/ext/kev/.venv/bin/python"
cd "$S/ext/kev"
export PYTHONPATH=.
declare -A SRC=([val]="$S/train_out/CLI11/samples.jsonl" [test_fmt]="$S/eval_fmt60/samples.jsonl" [test_lz4]="$S/eval_lz460/samples.jsonl" [test_entt]="$S/eval_entt60/samples.jsonl" [test_cxxopts]="$S/eval_cxxopts60/samples.jsonl")
declare -A JEV=([val]="$S/eval_cli60" [test_fmt]="$S/eval_fmt60" [test_lz4]="$S/eval_lz460" [test_entt]="$S/eval_entt60" [test_cxxopts]="$S/eval_cxxopts60")
OUT="$S/kev_data/compare-$TAG.txt"; : > "$OUT"
for set in val test_fmt test_lz4 test_entt test_cxxopts; do
  pred="$S/kev_data/pred-$TAG-$set.jsonl"
  "$PY" "$S/clangd_test/kev_local_eval.py" "$CKPT" "$S/kev_data/$set.jsonl" "$pred" >/dev/null 2>"$S/kev_data/pred-$TAG-$set.log"
  base="$S/kev_data/pred-base-$set.jsonl"; [ -f "$base" ] || base="-"
  { echo "=================== [$set] $TAG"; "$PY" -I "$S/clangd_test/compare_models.py" "${SRC[$set]}" "$S/kev_data/$set.jsonl" "$base" "$pred" "${JEV[$set]}"; echo; } | tee -a "$OUT"
done
