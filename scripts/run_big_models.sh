#!/bin/bash
# 사용: scripts/run_big_models.sh  (~/work/clangd-rerank 에서 실행; 결과는 eval_data/eval_gen_fresh_decl/<tag>-gen.jsonl, gen_report.py 로 채점)
# 큰 기반 모델 측정(학습 없음, 문맥 보강 켬): Coder-3B → 3.5-4B → 3.5-2B
cd ~/work/clangd-rerank
for m in "Qwen/Qwen2.5-Coder-3B coder25-3b" "Qwen/Qwen3.5-4B-Base qwen35-4b" "Qwen/Qwen3.5-2B-Base qwen35-2b"; do
  set -- $m
  echo "== $1 ($2) $(date +%H:%M)"
  ext/kev/.venv/bin/python ~/projects/clangd-rerank/scripts/gen_qwen.py ~/projects/clangd-rerank/eval_data/eval_gen_fresh_decl \
    --model "$1" --src-root eval_src_fresh --enrich --tag "$2-enrich" 2>&1 | grep -v "Loading weights\|causal_conv1d"
done
echo "== ALL DONE $(date +%H:%M)"
