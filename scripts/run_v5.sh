#!/usr/bin/env bash
# Sorter v5: 같은 이름의 한정 후보(std::string / std::pmr::string)를 모델이 직접 고르게 재학습한다.
#   v4 와 다른 점: 후보 열쇠 = 실제로 들어가는 글(CAND_KEY=insert), qual 자리(한정 이름을 지우고 이름만 1~3글자 친 상황) 추가.
#   소스·자리 뽑기·편향 규칙·학습 레시피는 v4 그대로 (기존 자리는 같은 시드로 뽑힌다).
# 사용: run_v5.sh collect | data | train | eval | all      (단계별로 다시 돌릴 수 있다)
#   collect : clangd 수집 (CPU만, 약 1~1.5시간) → ~/work/clangd-rerank/v5/{train_out,train_out2,train_out3,eval_out_fresh}
#   data    : 편향 규칙 선별 + Kev 형식 → kev_data/train_v5.jsonl, 신선 시험셋 v5/eval_fresh + eval_v5 입력
#   train   : GPU 학습 (v4 레시피, 약 5.5~6시간) → ext/kev/runs/clangd-0.8b-v5
#   eval    : v4(이름 묶음 / 한정 후보)·v5 를 신선 시험셋에서 비교 → results/compare-v5-fresh.txt
set -uo pipefail
P="$(cd "$(dirname "$0")" && pwd)"            # 이 저장소 scripts/
R="$(dirname "$P")"                            # 저장소 루트
W=$HOME/work/clangd-rerank
O=$W/v5
PY="$W/jevenv/bin/python -I"
KPY=$W/ext/kev/.venv/bin/python
JOBS=${JOBS:-6}
export CAND_KEY=insert EVAL_QUAL_PER_FILE=${EVAL_QUAL_PER_FILE:-10}
log(){ echo "[$(date '+%F %T')] $*"; }

collect() {
  mkdir -p $O/train_out $O/train_out2 $O/train_out3 $O/eval_out_fresh
  T=$W/train_src
  run() {  # collect_train.sh 의 라이브러리 6개 (v4 에 들어간 것만): run <이름> <루트> <파일당 상한> <파일...>
    local name=$1 root=$2 per=$3; shift 3
    local files; files=$(IFS=,; echo "$*")
    echo "== $name ($# files) $(EVAL_ROOT="$root" EVAL_TOPDOWN=1 EVAL_PER_FILE=$per EVAL_FILES="$files" $PY $P/eval_rerank.py collect "$O/train_out/$name" 2>&1 | tail -1)"
  }
  log "라이브러리 6개 (train_out)"
  (cd "$T/lua" && printf '%s\n' -xc -std=c99 -I. > compile_flags.txt
   run lua "$T/lua" 50 lapi.c lauxlib.c lbaselib.c lcode.c ldebug.c ldo.c lgc.c llex.c lobject.c lparser.c lstrlib.c ltable.c lvm.c) &
  (cd "$T/zstd" && printf '%s\n' -xc -std=c99 -Ilib -Ilib/common -Ilib/compress -Ilib/decompress > compile_flags.txt
   run zstd "$T/zstd" 50 lib/compress/zstd_compress.c lib/compress/zstd_lazy.c lib/compress/huf_compress.c lib/compress/fse_compress.c lib/decompress/zstd_decompress.c lib/decompress/zstd_decompress_block.c lib/common/entropy_common.c programs/fileio.c programs/zstdcli.c programs/benchzstd.c) &
  (cd "$T/tinyxml2" && printf '%s\n' -xc++ -std=c++17 -I. > compile_flags.txt
   run tinyxml2 "$T/tinyxml2" 120 tinyxml2.cpp xmltest.cpp) &
  (cd "$T/abseil-cpp" && printf '%s\n' -xc++ -std=c++17 -I. > compile_flags.txt
   run abseil "$T/abseil-cpp" 50 absl/strings/ascii.cc absl/strings/charconv.cc absl/strings/cord.cc absl/strings/escaping.cc absl/strings/numbers.cc absl/strings/str_cat.cc absl/strings/str_replace.cc absl/strings/str_split.cc absl/time/time.cc absl/time/duration.cc absl/container/internal/raw_hash_set.cc absl/synchronization/mutex.cc) &
  (cd "$T/json" && printf '%s\n' -xc++ -std=c++17 -Iinclude -Itests/thirdparty/doctest -Itests/src > compile_flags.txt
   run json "$T/json" 40 $(cd "$T/json" && ls tests/src/unit-*.cpp | head -14)) &
  (cd "$T/glm" && printf '%s\n' -xc++ -std=c++17 -I. > compile_flags.txt
   run glm "$T/glm" 40 $(cd "$T/glm" && ls test/core/core_func_*.cpp test/gtc/*.cpp 2>/dev/null | head -14)) &
  wait
  log "라이브러리 18개 (train_out2)"
  grep '^train_out2/' $R/train_v4_sources.txt | cut -d/ -f2 | sort -u | sed "s#^#$T/#" \
    | xargs -P $JOBS -I{} $PY $P/collect_auto.py $O/train_out2 {} 2>&1 | grep -v '^$'
  log "응용 프로젝트 (train_out3, train_src2 전체)"
  ls -d $W/train_src2/*/ | xargs -P $JOBS -I{} $PY $P/collect_auto.py $O/train_out3 {} 2>&1 | grep -v '^$'
  cp $W/train_out3/app_test_pick.json $O/train_out3/
  log "신선 시험셋 (eval_out_fresh)"
  ls -d $W/eval_src_fresh/*/ | xargs -P $JOBS -I{} $PY $P/collect_auto.py $O/eval_out_fresh {} 2>&1 | grep -v '^$'
  log "수집 끝: train_out $(cat $O/train_out/*/samples.jsonl | wc -l) / train_out2 $(cat $O/train_out2/*/samples.jsonl | wc -l) / train_out3 $(cat $O/train_out3/*/samples.jsonl | wc -l) / fresh $(cat $O/eval_out_fresh/*/samples.jsonl | wc -l) 위치"
}

data() {
  log "편향 규칙 선별 (build_v4.py, CAP 100 + QUAL_CAP ${QUAL_CAP:-15})"
  rm -rf $O/train_out3_sel $O/eval_app
  python3 -I $P/build_v4.py $O/train_out3 $O/train_out3/app_test_pick.json $O/train_out3_sel $O/eval_app | tail -3
  # 라이브러리 24개는 v4 와 같은 목록(경로만 v5 로), 응용은 이번 선별 결과 전부(v4 도 그랬다)
  { grep -v 'train_out3_sel/' $R/train_v4_sources.txt | sed "s#^train_out#$O/train_out#"; cat $O/train_out3_sel/sources.txt; } \
    | while read -r f; do [ -e "$f" ] && echo "$f" || echo "없음: $f" >&2; done > $O/train_v5_sources.txt
  log "Kev 형식: $(wc -l < $O/train_v5_sources.txt) 소스"
  $PY $P/to_kev_jsonl.py $W/kev_data/train_v5.jsonl $(cat $O/train_v5_sources.txt) | tail -1
  python3 -I - "$O" <<'PYEOF'
import json, sys, collections
O = sys.argv[1]
c = collections.Counter(); amb = 0; n = 0
for path in open(f"{O}/train_v5_sources.txt").read().split():
    for l in open(path):
        s = json.loads(l); c[s.get("kind", "ident")] += 1
print("학습 위치 종류:", {k: f"{v} ({100*v/sum(c.values()):.1f}%)" for k, v in c.most_common()})
PYEOF
  log "신선 시험셋 (build_fresh.py, CAP 90 + QUAL_CAP 15)"
  rm -rf $O/eval_fresh
  CAP=90 FRESH_SRC=$W/eval_src_fresh python3 -I $P/build_fresh.py $O/eval_out_fresh $O/eval_fresh $W/train_src $W/train_src2 | tail -3
  python3 -I $P/eval_v5.py build $O/eval_fresh/samples.jsonl $W/kev_data/test_fresh_v5
}

train() {
  local OUT=clangd-0.8b-v5 DATA=$W/kev_data/train_v5.jsonl
  cd $W/ext/kev
  if [ -e "runs/$OUT/adapter_model.safetensors" ]; then log "runs/$OUT 이미 있음"; return 1; fi
  rm -rf "runs/$OUT"
  log "학습 시작 data=$DATA ($(wc -l < $DATA)건) out=runs/$OUT (v4 레시피)"
  PYTHONPATH=. $KPY -m kev.train --data "$DATA" --init_from jaredpalmer/kev-0.8b --out "runs/$OUT" \
    --base Qwen/Qwen3.5-0.8B-Base --epochs 1 --batch 1 --accum 8 --dtype bf16 --checkpointing 1 --max_state 1400 \
    --p_none 0 --p_none_distract 0 --p_distract 0 --device cuda --lr 5e-5
  log "학습 끝"
}

evaluate() {
  cd $W/ext/kev
  export PYTHONPATH=.
  local K=$W/kev_data/test_fresh_v5
  for spec in "v4 name" "v4 ins" "v5 ins"; do
    set -- $spec
    [ -e runs/clangd-0.8b-$1 ] || { log "건너뜀: runs/clangd-0.8b-$1 없음"; continue; }
    log "평가 $1 ($2)"
    $KPY $P/kev_local_eval.py runs/clangd-0.8b-$1 $K-$2.jsonl $W/kev_data/pred-$1-test_fresh_v5-$2.jsonl > /dev/null 2>$W/kev_data/pred-$1-test_fresh_v5-$2.log
  done
  local args="v4-name=$W/kev_data/pred-v4-test_fresh_v5-name.jsonl v4+얕은쪽-name=$W/kev_data/pred-v4-test_fresh_v5-name.jsonl v4-ins=$W/kev_data/pred-v4-test_fresh_v5-ins.jsonl"
  [ -s $W/kev_data/pred-v5-test_fresh_v5-ins.jsonl ] && args="$args v5=$W/kev_data/pred-v5-test_fresh_v5-ins.jsonl"
  python3 -I $P/eval_v5.py report $O/eval_fresh/samples.jsonl $K $args | tee $R/results/compare-v5-fresh.txt
}

case "${1:-}" in
  collect) collect ;;
  data) data ;;
  train) train ;;
  eval) evaluate ;;
  all) collect && data && train && evaluate ;;
  *) sed -n 2,10p "$0"; exit 1 ;;
esac
