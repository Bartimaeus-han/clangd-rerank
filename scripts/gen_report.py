#!/usr/bin/env python3
"""식별자 생성 예측 채점. 사용: gen_report.py <samples.jsonl> <pred.jsonl> [<pred.jsonl> ...]

pred 줄: {"i","k","guesses":[...]} (claude_eval.py generate 출력, 나중에 Kev/기반 LM 출력도 같은 형식).
samples 는 collect_newident.py 출력(cls 필드 있음) 또는 eval 세트(cls 없으면 모두 cand 로 본다).
지표(분류 × 접두어): exact@1, exact@5, 서브토큰 F1@1 (대소문자 무시), 접두어 준수율, 그리고 cand 자리에서는 clangd R@1 도 같이 찍는다.
"""
import collections, json, re, sys

_SUB = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def subtok(s):
    return [t.lower() for t in _SUB.findall(s.replace("_", " "))]


def f1(a, b):
    a, b = subtok(a), subtok(b)
    if not a or not b:
        return 0.0
    ca, cb = collections.Counter(a), collections.Counter(b)
    inter = sum((ca & cb).values())
    if not inter:
        return 0.0
    p, r = inter / len(a), inter / len(b)
    return 2 * p * r / (p + r)


def main():
    samples = [json.loads(l) for l in open(sys.argv[1])]
    for pred_path in sys.argv[2:]:
        preds = {(r["i"], r["k"]): r for r in map(json.loads, open(pred_path))}
        agg = collections.defaultdict(lambda: collections.defaultdict(float))
        for i, s in enumerate(samples):
            cls = s.get("cls", "cand")
            for k, lv in s["levels"].items():
                r = preds.get((i, k))
                if r is None:
                    continue
                g = [x for x in r.get("guesses", []) if x]
                typed = s["gold"][:int(k)]
                a = agg[(cls, k)]
                a["n"] += 1
                a["e1"] += bool(g) and g[0] == s["gold"]
                a["e5"] += s["gold"] in g[:5]
                a["f1"] += f1(g[0], s["gold"]) if g else 0.0
                a["pre"] += all(x.startswith(typed) for x in g) if (typed and g) else 1.0
                a["empty"] += not g
                a["clangd1"] += bool(lv["cands"]) and lv["cands"][0]["name"] == s["gold"]
                # 절약 타수: 남은 글자 수 - 고르는 비용(1위 Tab 1타, r위는 아래 r-1번 + 1타). 목록에 없으면 0 (그냥 친다).
                rem = len(s["gold"]) - int(k)
                a["rem"] += rem
                if s["gold"] in g[:5]:
                    a["saved"] += max(0, rem - g.index(s["gold"]) - 1)
        print(f"== {pred_path} ({len(preds)}건)")
        print(f"{'분류':<6}{'k':>2}{'n':>6}{'exact@1':>9}{'exact@5':>9}{'subF1@1':>9}{'접두어OK':>9}{'빈응답':>7}{'clangd@1':>9}{'절약타수':>10}")
        for cls in ("decl", "new", "miss", "cand"):
            for k in ("0", "1", "2"):
                a = agg.get((cls, k))
                if not a:
                    continue
                n = a["n"]
                print(f"{cls:<6}{k:>2}{int(n):>6}{100 * a['e1'] / n:>8.1f}%{100 * a['e5'] / n:>8.1f}%{100 * a['f1'] / n:>8.1f}%"
                      f"{100 * a['pre'] / n:>8.1f}%{int(a['empty']):>7}{100 * a['clangd1'] / n:>8.1f}%"
                      f"{a['saved'] / n:>5.1f}/{a['rem'] / n:.1f}")
        print()


if __name__ == "__main__":
    main()
