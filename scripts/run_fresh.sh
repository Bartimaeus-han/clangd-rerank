#!/usr/bin/env bash
# 신선 시험셋(2026-03 이후 생성 저장소) 파이프라인:
#   clone 완료 대기 → clangd 샘플 수집(병렬 4) → build_fresh.py(중복·번들 제외, 주제당 90) → Kev 형식
#   → v4·v2-e1 평가 → Jev(상위 60, 40줄) → 비교표 kev_data/compare-{v4,v2e1}-fresh.txt
set -uo pipefail
S="$(cd "$(dirname "$0")" && pwd)"
W=$HOME/work/clangd-rerank
SRC=$W/eval_src_fresh; OUT=$W/eval_out_fresh; EV=$W/eval_fresh; EV60=$W/eval_fresh60
PY=$S/jevenv/bin/python; KPY=$S/ext/kev/.venv/bin/python
log(){ echo "[$(date +%H:%M:%S)] $*"; }
while pgrep -f 'collect_githu[b].py' >/dev/null; do sleep 15; done
log "clone 완료: $(ls -d $SRC/*/ | wc -l) 저장소"
mkdir -p $OUT
ls -d $SRC/*/ | xargs -P 4 -I{} $PY -I $S/clangd_test/collect_auto.py $OUT {} 2>&1 | grep -v '^$'
log "수집 완료: $(ls $OUT | wc -l) 프로젝트, 위치 $(cat $OUT/*/samples.jsonl 2>/dev/null | wc -l)"
rm -rf $EV; CAP=90 python3 -I $S/clangd_test/build_fresh.py $OUT $EV $W/train_src $W/train_src2 || { log "FAIL build_fresh"; exit 1; }
$PY -I $S/clangd_test/to_kev_jsonl.py $W/kev_data/test_fresh.jsonl $EV/samples.jsonl | tail -1
ln -sfn $EV $S/eval_fresh
cd $S/ext/kev; export PYTHONPATH=.
for tag in v4 v2-e1; do
  t=${tag//-/}; ck=$S/ext/kev/runs/clangd-0.8b-$tag
  $KPY $S/clangd_test/kev_local_eval.py $ck $W/kev_data/test_fresh.jsonl $W/kev_data/pred-$t-test_fresh.jsonl >/dev/null 2>$W/kev_data/pred-$t-test_fresh.log \
    && log "평가 완료 $t" || log "FAIL 평가 $t (kev_data/pred-$t-test_fresh.log)"
done
# Jev: 세 접두어 모두 상위 60 안인 위치만, 문맥 40줄 (eval_app60_sub 와 같은 규칙)
EV=$EV EV60=$EV60 python3 -I - <<'PYEOF'
import json, os
EV=os.environ["EV"]; EV60=os.environ["EV60"]; os.makedirs(EV60, exist_ok=True)
kept=tot=0
with open(f"{EV60}/samples.jsonl","w") as out:
    for l in open(f"{EV}/samples.jsonl"):
        s=json.loads(l); tot+=1
        if not all(s["gold"] in [c["name"] for c in lv["cands"][:60]] for lv in s["levels"].values()): continue
        for lv in s["levels"].values():
            lv["cands"]=lv["cands"][:60]
            pre=lv["state"].split("<CURSOR>")[0].split("\n")
            lv["state"]="\n".join(pre[-40:])+"<CURSOR>"
        out.write(json.dumps(s)+"\n"); kept+=1
print(f"eval_fresh60: {kept}/{tot}곳 (세 접두어 모두 상위 60 안)")
PYEOF
ln -sfn $EV60 $S/eval_fresh60
(cd $S && ./run_jev.sh eval_fresh60 2>&1 | tail -20) && log "Jev 완료" || log "Jev 실패(건너뜀)"
JEV=""; [ -s $EV60/jev.jsonl ] && JEV=$EV60
for t in v4 v2e1; do
  [ -s $W/kev_data/pred-$t-test_fresh.jsonl ] || continue
  { echo "=================== [fresh] $t"; $KPY -I $S/clangd_test/compare_models.py $EV/samples.jsonl $W/kev_data/test_fresh.jsonl - $W/kev_data/pred-$t-test_fresh.jsonl $JEV; } | tee $W/kev_data/compare-$t-fresh.txt
done
log DONE
