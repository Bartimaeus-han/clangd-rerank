"""생성 서버(8010) 지연 측정: 신선 decl 샘플 60곳을 실제 파일 앞부분(보강 포함)으로 0글자·1글자 요청. 중앙값/p90/최대."""
import json, os, statistics, sys, time, urllib.request
root = os.path.expanduser("~/work/clangd-rerank/eval_src_fresh")
rows = [json.loads(l) for l in open(os.path.expanduser("~/projects/clangd-rerank/eval_data/eval_gen_fresh_decl/samples.jsonl"))]
rows = [r for r in rows if r["cls"] == "decl"][:60]
def ask(prefix, typed):
    t0 = time.perf_counter()
    r = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8010/v1/gen", data=json.dumps({"prefix": prefix, "typed": typed, "n": 3}).encode(),
                                                      headers={"content-type": "application/json"}), timeout=20)
    g = json.load(r)["guesses"]; return (time.perf_counter() - t0) * 1000, g
out = {0: [], 1: []}; hit = {0: 0, 1: 0}; lens = []
for r in rows:
    L = open(os.path.join(root, r["proj"], r["file"]), errors="ignore").read().split("\n")
    before = "\n".join(L[:r["line"]] + [L[r["line"]][:r["col"]]]); lens.append(len(before.split("\n")))
    for k in (0, 1):
        ms, g = ask(before[:-k] if k else before, r["gold"][:k]); out[k].append(ms); hit[k] += bool(g) and g[0] == r["gold"]
for k in (0, 1):
    v = sorted(out[k]); print(f"{k}글자: 중앙값 {statistics.median(v):.0f}ms  p90 {v[int(len(v)*0.9)]:.0f}ms  최대 {v[-1]:.0f}ms  1위 정답 {hit[k]}/{len(v)}")
print(f"커서 앞 줄 수 중앙값 {statistics.median(lens):.0f}")
