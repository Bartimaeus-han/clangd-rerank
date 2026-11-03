#!/usr/bin/env bash
# Claude API 재정렬/생성 실험. 키는 프로젝트 루트의 claude.env (ANTHROPIC_API_KEY=...) 에서 읽는다 (.gitignore 됨).
# 사용: run_claude.sh rerank|generate eval_<이름> [claude_eval.py 옵션...]
#   예) run_claude.sh rerank eval_cli60 --dry-run              비용 추정만
#       run_claude.sh rerank eval_cli60 --limit 30             30곳 시범
#       MODEL=claude-haiku-5-5 run_claude.sh rerank eval_fresh60
#       run_claude.sh generate eval_cli60
#       run_claude.sh compare eval_cli60 --ref "Kev v4=73.7/89.1/93.6"   clangd/Jev/Claude 모델별 성능·비용 한 표
# rerank 뒤에는 eval_rerank.py report 를 Claude 결과 파일로 돌려 clangd 와 비교표를 찍는다.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f claude.env ] && { set -a; . ./claude.env; set +a; }
PY=${JEVENV_PY:-$HOME/work/clangd-rerank/jevenv/bin/python}
MODEL=${MODEL:-claude-opus-5-5}
mode=$1; dir=$2; shift 2
[[ "$dir" =~ ^eval_[A-Za-z0-9_]+$ ]] || { echo "사용: run_claude.sh rerank|generate|compare eval_<이름> [옵션]" >&2; exit 2; }
if [ "$mode" = compare ]; then
  exec "$PY" -I scripts/claude_eval.py compare "eval_data/$dir" "$@"
fi
if [ "$mode" = genmatch ]; then
  exec "$PY" -I scripts/claude_eval.py genmatch "eval_data/$dir" --model "$MODEL" "$@"
fi
"$PY" -I scripts/claude_eval.py "$mode" "eval_data/$dir" --model "$MODEL" "$@"
if [ "$mode" = rerank ] && [ -f "eval_data/$dir/$MODEL.jsonl" ]; then
  RERANK_FILE="$MODEL.jsonl" RERANK_LABEL="$MODEL" "$PY" -I scripts/eval_rerank.py report "eval_data/$dir"
fi
if [ "$mode" = generate ] && [ -f "eval_data/$dir/$MODEL-gen.jsonl" ]; then
  "$PY" -I scripts/gen_report.py "eval_data/$dir/samples.jsonl" "eval_data/$dir/$MODEL-gen.jsonl"
  "$PY" -I scripts/claude_eval.py genmatch "eval_data/$dir" --model "$MODEL"
fi
