#!/usr/bin/env python3
"""Namer 서버(POST /v1/gen)를 HTTP 로 채점한다. 엔진이 달라도 같은 요청·같은 시험셋으로 비교하려는 것.

사용: gen_http_eval.py <dir> --tag <이름> [--url http://127.0.0.1:8010] [--src-root ~/work/clangd-rerank/eval_src_fresh] [--n 5]
  <dir>/samples.jsonl 의 자리마다 접두어 0/1/2글자로, 프록시와 똑같이 '파일 시작~커서 앞(친 글자 제외)' 을 prefix 로 보낸다.
출력: <dir>/<tag>-gen.jsonl  {"i","k","guesses","ms"}  (gen_report.py 형식; 이미 된 (i,k)는 건너뛴다)
끝에 지연(클라이언트 왕복) 중앙값/p90/최대를 접두어별로 찍는다. 채점은 gen_report.py <dir>/samples.jsonl <dir>/<tag>-gen.jsonl.
"""
import argparse, json, os, statistics, time, urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--tag", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--src-root", default=os.path.expanduser("~/work/clangd-rerank/eval_src_fresh"))
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    samples = [json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))]
    if a.limit:
        samples = samples[:a.limit]
    out = os.path.join(a.dir, f"{a.tag}-gen.jsonl")
    done = {(r["i"], r["k"]) for r in map(json.loads, open(out))} if os.path.exists(out) else set()
    lat = {}
    with open(out, "a") as f:
        for i, s in enumerate(samples):
            path = os.path.join(a.src_root, s["proj"], s["file"])
            try:
                L = open(path, errors="ignore").read().split("\n")
                full = "\n".join(L[:s["line"]] + [L[s["line"]][:s["col"]]])
            except OSError:
                full = None
            for k, lv in s["levels"].items():
                if (i, k) in done:
                    continue
                typed = s["gold"][:int(k)]
                before = full if full is not None else lv["state"].split("<CURSOR>")[0][:len(lv["state"].split("<CURSOR>")[0]) - len(typed)]
                body = json.dumps({"prefix": before, "typed": typed, "n": a.n}).encode()
                t0 = time.perf_counter()
                with urllib.request.urlopen(urllib.request.Request(a.url + "/v1/gen", data=body, headers={"content-type": "application/json"}), timeout=60) as r:
                    res = json.load(r)
                ms = (time.perf_counter() - t0) * 1000
                lat.setdefault(k, []).append(ms)
                f.write(json.dumps({"i": i, "k": k, "guesses": res.get("guesses", [])[:5], "ms": ms, "server_ms": res.get("ms")}) + "\n")
    for k, v in sorted(lat.items()):
        v.sort()
        print(f"{k}글자: {len(v)}건 중앙값 {statistics.median(v):.0f}ms  p90 {v[int(len(v) * 0.9)]:.0f}ms  최대 {v[-1]:.0f}ms")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
