"""서빙 경로 측정: 떠 있는 kev.serve(또는 Jev 호환 서버)에 Kev JSONL 질의를 순서대로 보내 왕복 지연과 R@1을 잰다.

사용: serve_bench.py <kev_jsonl> [N=200] [base_url=http://127.0.0.1:8009]
출력: 건수, R@1, 지연 중앙값/p90/최소, 실패 수. 워밍업 3건은 통계에서 뺀다.
"""
import json, sys, time, urllib.request


def main():
    path = sys.argv[1]
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    base = (sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8009").rstrip("/")
    recs = [json.loads(l) for l in open(path)][:N + 3]
    ms, hits, fails = [], 0, 0
    for j, r in enumerate(recs):
        q = r["questions"]["next"]
        body = json.dumps({"model": "kev-latest", "state": r["state"],
                           "questions": {"next": {"type": "choice", "instructions": q["instructions"], "criteria": q["criteria"]}}}).encode()
        req = urllib.request.Request(base + "/v1/systemone", data=body, method="POST",
                                     headers={"content-type": "application/json", "authorization": "Bearer local"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                probs = json.load(resp)["answers"]["next"]["probabilities"]
        except Exception as e:
            fails += 1
            if fails <= 3:
                print("fail:", type(e).__name__, str(e)[:150], file=sys.stderr)
            continue
        dt = (time.perf_counter() - t0) * 1000
        if j < 3:
            continue
        ms.append(dt)
        gold = q.get("label") or r.get("label")
        names = list(q["criteria"])
        top = max(names, key=lambda n: (probs.get(n, 0.0), -names.index(n)))
        hits += top == gold
    ms.sort()
    n = len(ms)
    qq = lambda p: ms[min(n - 1, int(p * n))] if n else 0
    print(f"{path.split('/')[-1]}: n={n} R@1={100*hits/max(1,n):.1f}% 지연 중앙값 {qq(.5):.0f}ms p90 {qq(.9):.0f}ms 최소 {ms[0] if ms else 0:.0f}ms 실패 {fails}")


if __name__ == "__main__":
    main()
