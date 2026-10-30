"""Kev 체크포인트를 학습 때와 같은 길이 한도로 로컬 평가한다 (kev.benchmark --data는 기본 한도로 절반을 버린다).

Kev venv의 파이썬으로 실행: kev_local_eval.py <체크포인트> <kev_jsonl> <출력.jsonl>
출력: 줄마다 {"i", "probs", "ms"} (입력 순서 그대로). 지표 계산은 eval_rerank.py report가 읽는 jev.jsonl 형식으로 맞춘다.
"""
import json, os, sys, time

from kev.data import load_records
from kev.model import ContextOverflow, training_context
from kev.predictors import LocalPredictor


def main():
    run, data, out_path = sys.argv[1:4]
    pred = LocalPredictor(run, "cuda", context=training_context(1400))
    recs = load_records(data)
    # 이어서 실행: 이미 끝난 i 는 건너뛴다
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["i"] for l in open(out_path)}
    with open(out_path, "a") as out:
        for i, rec in enumerate(recs):
            if i in done:
                continue
            t0 = time.perf_counter()
            try:
                p = pred(rec)
            except ContextOverflow as e:  # 길이 한도를 넘는 항목은 빈 결과로 남긴다 (비교 때 제외)
                out.write(json.dumps({"i": i, "probs": None, "ms": None, "error": str(e)[:120]}) + "\n")
                continue
            ms = (time.perf_counter() - t0) * 1000
            out.write(json.dumps({"i": i, "probs": p["probabilities"]["next"], "ms": ms}) + "\n")
            if (i + 1) % 500 == 0:
                print(f"  {i + 1}/{len(recs)}", flush=True)


if __name__ == "__main__":
    main()
