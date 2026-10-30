#!/usr/bin/env bash
# v4 학습: train_v4.jsonl(v2 24 라이브러리 + 219 응용 프로젝트 + codecontests ≤1,000; 99,308건), v2 레시피 그대로.
# 사용: train_v4.sh [<데이터.jsonl>] [<출력 이름>]   기본 kev_data/train_v4.jsonl, runs/clangd-0.8b-v4
set -euo pipefail
S="$(cd "$(dirname "$0")" && pwd)"
DATA=${1:-$S/kev_data/train_v4.jsonl}; OUT=${2:-clangd-0.8b-v4}
cd "$S/ext/kev"
if [ -e "runs/$OUT/adapter_model.safetensors" ]; then echo "runs/$OUT 이미 있음"; exit 1; fi
rm -rf "runs/$OUT"
echo "start $(date '+%F %T') data=$DATA ($(wc -l < "$DATA")건) out=runs/$OUT"
PYTHONPATH=. exec .venv/bin/python -m kev.train --data "$DATA" --init_from jaredpalmer/kev-0.8b --out "runs/$OUT" \
  --base Qwen/Qwen3.5-0.8B-Base --epochs 1 --batch 1 --accum 8 --dtype bf16 --checkpointing 1 --max_state 1400 \
  --p_none 0 --p_none_distract 0 --p_distract 0 --device cuda --lr 5e-5
