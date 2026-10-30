#!/usr/bin/env bash
# v4 학습(kev.train)이 끝나기를 기다렸다가 체크포인트가 있으면 eval_full.sh 로 평가한다 (setsid 로 띄워 세션과 무관하게 돈다).
# pgrep 패턴의 [n] 은 이 스크립트/감시 셸 자신의 명령줄에 걸리지 않게 하려는 것.
S="$(cd "$(dirname "$0")" && pwd)"
while pgrep -f "python -m kev\.trai[n]" >/dev/null; do sleep 60; done
echo "train ended $(date '+%F %T')"
if [ -e "$S/ext/kev/runs/clangd-0.8b-v4/adapter_model.safetensors" ]; then
  echo "eval start $(date '+%F %T')"
  "$S/clangd_test/eval_full.sh" "$S/ext/kev/runs/clangd-0.8b-v4" v4
  echo "eval end $(date '+%F %T')"
else
  echo "NO_CHECKPOINT"
fi
