#!/usr/bin/env bash
# 새 세션(또는 /tmp 가 비워진 뒤)에 scratchpad 작업 구조를 되살린다: 디스크(~/work/clangd-rerank)의 폴더를 심볼릭 링크로 걸고 스크립트를 복사한다.
# 사용: restore_scratchpad.sh <scratchpad 경로>
set -euo pipefail
S=${1:?scratchpad 경로}; W=~/work/clangd-rerank; R="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$S/clangd_test" "$S/ext" "$S/kev_data"
[ -e "$S/ext/kev" ] || ln -s "$W/ext/kev" "$S/ext/kev"
for d in "$W"/eval_* "$W"/train_out* "$W"/train_src* "$W"/sweep "$W"/jevenv; do [ -e "$S/$(basename "$d")" ] || ln -s "$d" "$S/$(basename "$d")"; done
for f in "$W"/kev_data/*; do [ -e "$S/kev_data/$(basename "$f")" ] || ln -s "$f" "$S/kev_data/$(basename "$f")"; done
cp "$R"/scripts/*.py "$R"/scripts/eval_ckpt.sh "$R"/scripts/eval_full.sh "$R"/scripts/eval_s2.sh "$R"/scripts/collect_train.sh "$S/clangd_test/"
cp "$R"/scripts/serve_kev.sh "$R"/scripts/run_jev.sh "$R"/scripts/train_v4.sh "$R"/results/OVERNIGHT_PLAN.md "$S/"
echo "복구 완료: $S (Jev 키는 $S/jev.env 에 TYPESAFE_API_KEY=... 로 다시 넣어야 run_jev.sh 가 돈다)"
