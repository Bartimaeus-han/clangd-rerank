#!/bin/bash
# 출시 가능 라이선스(Apache-2.0) 후보: Coder-1.5B(bf16) → Coder-7B(NF4 4bit). 보강 켬, 학습 없음.
cd ~/work/clangd-rerank
run() { echo "== $1 ($2) $(date +%H:%M)"; ext/kev/.venv/bin/python ~/projects/clangd-rerank/scripts/gen_qwen.py ~/projects/clangd-rerank/eval_data/eval_gen_fresh_decl \
    --model "$1" --src-root eval_src_fresh --enrich --tag "$2-enrich" $3 2>&1 | grep -v "Loading weights\|causal_conv1d\|Fetching"; }
run Qwen/Qwen2.5-Coder-1.5B coder25-1.5b
run Qwen/Qwen2.5-Coder-7B coder25-7b-4bit --load-4bit
echo "== ALL DONE $(date +%H:%M)"
