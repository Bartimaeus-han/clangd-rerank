"""실사용 측정 파일(RERANK_STATS, clangd_rerank_proxy.py 가 쓴 JSONL)을 집계한다.

사용: rerank_stats.py <stats.jsonl> [<stats.jsonl> ...]
출력: 친 글자 수(0/1/2+)별로 자리 수, 후보 안에 정답이 있던 비율, clangd / 2단계 / 최종 순서의 R@1·R@5·MRR.
      (오프라인 평가와 같은 기준: '사용자가 결국 쓴 식별자'가 정답. 후보에 없던 자리는 R@1 분모에 넣고 MRR 0 으로 센다.)
"""
import collections, json, sys


def main():
    rows = [json.loads(l) for p in sys.argv[1:] for l in open(p) if l.strip()]
    by = collections.defaultdict(list)
    for r in rows:
        by[min(r["typed"], 2)].append(r)
    orders = ["clangd", "stage2", "final"]
    print(f"{'친 글자':<7}{'자리':>6}{'후보에 있음':>11} | " + " | ".join(f"{o:^22}" for o in orders))
    print(f"{'':<7}{'':>6}{'':>11} | " + " | ".join(f"{'R@1':>6}{'R@5':>7}{'MRR':>7}  " for _ in orders))
    for t in sorted(by):
        rs = by[t]
        n = len(rs)
        has = sum(1 for r in rs if r["rank"]["clangd"] is not None)
        cells = []
        for o in orders:
            ranks = [r["rank"].get(o) for r in rs if o in r["rank"]]
            if not ranks:
                cells.append(f"{'-':^22}")
                continue
            m = len(ranks)
            r1 = sum(1 for k in ranks if k == 1) / m
            r5 = sum(1 for k in ranks if k is not None and k <= 5) / m
            mrr = sum(1 / k for k in ranks if k is not None) / m
            cells.append(f"{100*r1:>5.1f}%{100*r5:>6.1f}%{mrr:>7.3f}  ")
        label = f"{t}글자" if t < 2 else "2글자+"
        print(f"{label:<7}{n:>6}{100*has/max(1,n):>10.1f}% | " + " | ".join(cells))
    print(f"총 {len(rows)}줄, 파일 {len({r['file'] for r in rows})}개")


if __name__ == "__main__":
    main()
