#!/usr/bin/env python3
"""식별자 생성 기준선: 커서 앞 문맥에서 가장 최근에 나온 식별자 5개(접두어 맞는 것만, 키워드 제외)를 그대로 추측한다.
사용: gen_baseline.py <dir>  →  <dir>/baseline-gen.jsonl ({"i","k","guesses"}) → gen_report.py 로 채점.
선언 자리(decl)에서 이 기준선이 거의 0점이어야 '새 이름 생성'이 정말 필요한 자리라는 뜻이다."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_rerank as er  # noqa: E402

IDENT = re.compile(r"[A-Za-z_]\w*")


def main():
    d = sys.argv[1]
    samples = [json.loads(l) for l in open(os.path.join(d, "samples.jsonl"))]
    with open(os.path.join(d, "baseline-gen.jsonl"), "w") as f:
        for i, s in enumerate(samples):
            for k, lv in s["levels"].items():
                typed = s["gold"][:int(k)]
                before = lv["state"].split("<CURSOR>")[0]
                if typed:
                    before = before[:-len(typed)]
                seen, g = set(), []
                for w in reversed(IDENT.findall(before)):
                    if w in er.KEYWORDS or w in seen or not w.startswith(typed) or w.isdigit():
                        continue
                    seen.add(w); g.append(w)
                    if len(g) == 5:
                        break
                f.write(json.dumps({"i": i, "k": k, "guesses": g}) + "\n")
    print("baseline-gen.jsonl 저장:", len(samples), "곳")


if __name__ == "__main__":
    main()
