"""v5(한정 이름 후보) 평가: 같은 자리에서 '이름 묶음'(v4 방식)과 '한정 이름 후보'(v5 방식)를 비교한다.

사용:
  eval_v5.py build  <samples.jsonl> <out_prefix>
      CAND_KEY=insert 로 수집한 samples 에서 두 Kev 입력을 만든다.
        <out_prefix>-ins.jsonl  : 후보 = 한정 열쇠(std::string, std::pmr::string ...), 정답 = 한정 열쇠
        <out_prefix>-name.jsonl : 후보 = 이름으로 묶음(v4 학습 형식), 정답 = 이름
        <out_prefix>-map.jsonl  : 줄마다 {"s": 샘플 번호, "k": 친 글자 수} (두 파일의 줄 번호가 같다)
      두 형식 모두에서 정답이 상위 MAX_CANDS 안인 (자리, 글자 수)만 남긴다.
  eval_v5.py report <samples.jsonl> <out_prefix> [이름=<pred.jsonl> ...]
      이름이 *-name 으로 끝나는 pred 는 -name.jsonl 로 돌린 결과로 보고(이름을 고른 뒤 같은 이름 안에서는 clangd 순서),
      그 밖은 -ins.jsonl 결과로 본다. pred 는 kev_local_eval.py 출력.
      표: 1위 정답률(R@1) — 위치 종류별 × 친 글자 수, 그리고 '같은 이름 후보가 2개 이상인 자리'(애매 자리).
"""
import collections, json, os, re, sys

INSTRUCTIONS = "C++ code with a <CURSOR> marker. Which identifier will the programmer most likely type at <CURSOR>?"
CTX_LINES = int(os.environ.get("CTX_LINES", "40"))
MAX_CANDS = int(os.environ.get("MAX_CANDS", "60"))


def base(c):
    return c.get("base") or c["name"]


def depth(c):
    return re.split(r"[(<]", c["detail"].split(" -> ")[0], maxsplit=1)[0].count("::")


def views(lv):
    """(한정 후보 상위 N, 이름 묶음 상위 N [이름, 그 이름의 후보들(clangd 순서)])"""
    ins = lv["cands"][:MAX_CANDS]
    groups = {}
    for c in lv["cands"]:
        groups.setdefault(base(c), []).append(c)
    names = list(groups)[:MAX_CANDS]
    return ins, names, groups


def short_state(state):
    pre = state.split("<CURSOR>")[0]
    before, cursor = pre.rsplit("\n", 1) if "\n" in pre else ("", pre)
    return "\n".join(before.split("\n")[-(CTX_LINES - 1):] + [cursor + "<CURSOR>"])


def rows(samples):
    """(샘플 번호, 글자 수, 정답 열쇠, 정답 이름, 한정 후보, 이름 목록, 이름 묶음)"""
    for si, s in enumerate(samples):
        gold = s["gold"]
        for k, lv in sorted(s["levels"].items()):
            ins, names, groups = views(lv)
            gc = next((c for c in lv["cands"] if c["name"] == gold), None)
            if gc is None or gold not in [c["name"] for c in ins] or base(gc) not in names:
                continue
            yield si, k, gold, base(gc), ins, names, groups, lv


def build(samples_path, prefix):
    samples = [json.loads(l) for l in open(samples_path)]
    n = 0
    with open(prefix + "-ins.jsonl", "w") as fi, open(prefix + "-name.jsonl", "w") as fn, open(prefix + "-map.jsonl", "w") as fm:
        for si, k, gold, gname, ins, names, groups, lv in rows(samples):
            st = short_state(lv["state"])
            q = lambda crit, label: {"state": st, "questions": {"next": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": crit, "label": label}}}
            fi.write(json.dumps(q({c["name"]: c["detail"] for c in ins}, gold)) + "\n")
            fn.write(json.dumps(q({nm: groups[nm][0]["detail"] for nm in names}, gname)) + "\n")
            fm.write(json.dumps({"s": si, "k": k}) + "\n")
            n += 1
    print(f"{prefix}-{{ins,name,map}}.jsonl: {n}건")


def report(samples_path, prefix, specs):
    samples = [json.loads(l) for l in open(samples_path)]
    R = list(rows(samples))
    preds = {}
    for spec in specs:
        label, path = spec.split("=", 1)
        preds[label] = {r["i"]: r for r in map(json.loads, open(path))}
    methods = ["clangd", "clangd+얕은쪽"] + list(preds)
    hit = collections.defaultdict(lambda: collections.Counter())
    tot = collections.Counter()
    for i, (si, k, gold, gname, ins, names, groups, lv) in enumerate(R):
        kind = samples[si].get("kind", "ident")
        amb = len(groups[gname]) > 1
        cells = [(kind, k), (kind, "*"), ("전체", k), ("전체", "*")] + ([("애매", k), ("애매", "*")] if amb else [])
        pick = {"clangd": ins[0]["name"],
                "clangd+얕은쪽": sorted(groups[base(ins[0])], key=depth)[0]["name"]}
        ok = True
        for label, P in preds.items():
            p = P.get(i)
            if not p or not p.get("probs"):
                ok = False
                break
            pr = p["probs"]
            if label.endswith("-name"):
                nm = max(names, key=lambda x: (pr.get(x, 0.0), -names.index(x)))
                grp = groups[nm]
                pick[label] = (sorted(grp, key=depth)[0] if label.endswith("+얕은쪽-name") else grp[0])["name"]
            else:
                pick[label] = max(ins, key=lambda c: (pr.get(c["name"], 0.0), -ins.index(c)))["name"]
        if not ok:  # 한 모델이라도 빠진 항목(길이 초과 등)은 모두에서 뺀다
            continue
        for cell in cells:
            tot[cell] += 1
            for m in methods:
                hit[cell][m] += pick[m] == gold
    ks = sorted({c[1] for c in tot if c[1] != "*"}) + ["*"]
    kinds = [x for x in ["전체", "애매", "qual", "ident", "member", "scope"] if any((x, k) in tot for k in ks)]
    w = max(len(m) for m in methods) + 2
    print(f"1위 정답률 R@1 (%). '애매' = 같은 이름 후보(std::string / std::pmr::string 등)가 2개 이상인 자리. 괄호는 건수.")
    for kind in kinds:
        print(f"\n[{kind}]")
        print(" " * w + "".join(f"{('글자 ' + k) if k != '*' else '합계':>14}" for k in ks))
        for m in methods:
            print(f"{m:<{w}}" + "".join(f"{(100 * hit[(kind, k)][m] / tot[(kind, k)]) if tot[(kind, k)] else float('nan'):>8.1f}({tot[(kind, k)]:>4})" for k in ks))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(sys.argv[2], sys.argv[3])
    elif cmd == "report":
        report(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        sys.exit(__doc__)
