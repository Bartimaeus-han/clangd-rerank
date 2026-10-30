"""clangd / 학습 전 Kev-0.8B / 학습 후 Kev-0.8B / Jev 를 같은 위치에서 비교한다.

사용: compare_models.py <samples.jsonl> <kev_jsonl> <pred-base.jsonl> <pred-ft.jsonl> [<jev_dir>]
  samples.jsonl : clangd 샘플 (kev_jsonl을 만든 원본)
  kev_jsonl     : to_kev_jsonl.py 출력 (pred 파일의 i 는 이 파일의 줄 번호)
  pred-*.jsonl  : kev_local_eval.py 출력
  jev_dir       : (선택) 같은 위치에 Jev를 돌린 eval_ 폴더. (file,line,col)로 맞춘다.
to_kev_jsonl.py 와 같은 규칙(상위 MAX_CANDS, 정답 없으면 제외)으로 i 를 (위치, 접두어)에 되돌린다.
"""
import json, os, sys

MAX_CANDS = int(os.environ.get("MAX_CANDS", "60"))
PREFIXES = ("0", "1", "2")


def load_preds(path):
    out = {}
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            out[r["i"]] = r
    return out


def jev_lookup(jev_dir):
    """(file,line,col,k) -> Jev 확률 dict"""
    if not jev_dir:
        return {}
    S = [json.loads(l) for l in open(os.path.join(jev_dir, "samples.jsonl"))]
    J = {}
    for l in open(os.path.join(jev_dir, "jev.jsonl")):
        r = json.loads(l)
        s = S[r["i"]]
        J[(s.get("project", ""), s["file"], s["line"], s["col"], r["k"])] = r["probs"]
    return J


def top(names, probs):
    return max(names, key=lambda n: (probs.get(n, 0.0), -names.index(n)))


def main():
    samples_path, kev_path, base_path, ft_path = sys.argv[1:5]
    jev_dir = sys.argv[5] if len(sys.argv) > 5 else None
    samples = [json.loads(l) for l in open(samples_path)]
    n_kev = sum(1 for _ in open(kev_path))
    ft, jev = load_preds(ft_path), jev_lookup(jev_dir)
    base = load_preds(base_path) if base_path != "-" else ft  # "-" 면 학습 전 열 없이 비교

    # pred i -> (sample, k): to_kev_jsonl.py 와 같은 순서와 제외 규칙
    index = []
    for s in samples:
        for k in PREFIXES:
            lv = s["levels"][k]
            if s["gold"] in [c["name"] for c in lv["cands"][:MAX_CANDS]]:
                index.append((s, k))
    assert len(index) == n_kev, f"매핑 불일치: {len(index)} vs {n_kev}"

    cols = ["clangd"] + (["base"] if base_path != "-" else []) + ["ft"] + (["jev"] if jev else [])
    stats = {k: {c: {"r1": 0, "rr": 0.0, "r5": 0} for c in cols} | {"n": 0} for k in PREFIXES}
    by_kind = {}
    ms = {"base": [], "ft": []}
    for i, (s, k) in enumerate(index):
        if i not in base or i not in ft or base[i]["probs"] is None or ft[i]["probs"] is None:
            continue  # 아직 평가가 안 끝났거나 길이 한도를 넘어 건너뛴 항목
        names = [c["name"] for c in s["levels"][k]["cands"][:MAX_CANDS]]
        gold = s["gold"]
        picks = {"clangd": names, "ft": sorted(names, key=lambda n: (-ft[i]["probs"].get(n, 0), names.index(n)))}
        if "base" in cols:
            picks["base"] = sorted(names, key=lambda n: (-base[i]["probs"].get(n, 0), names.index(n)))
        key = (s.get("project", ""), s["file"], s["line"], s["col"], k)
        if jev:
            if key not in jev:
                continue
            picks["jev"] = sorted(names, key=lambda n: (-jev[key].get(n, 0), names.index(n)))
        st = stats[k]
        st["n"] += 1
        for c in cols:
            r = picks[c].index(gold) + 1
            st[c]["r1"] += r == 1
            st[c]["rr"] += 1 / r
            st[c]["r5"] += r <= 5
        kind = s.get("kind", "ident")
        bk = by_kind.setdefault((kind, k), {c: 0 for c in cols} | {"n": 0})
        bk["n"] += 1
        for c in cols:
            bk[c] += picks[c][0] == gold
        ms["base"].append(base[i]["ms"])
        ms["ft"].append(ft[i]["ms"])

    label = {"clangd": "clangd", "base": "Kev-0.8B 학습 전", "ft": "Kev-0.8B 학습 후", "jev": "Jev"}
    pct = lambda a, n: f"{100 * a / n:5.1f}%" if n else "   - "
    print(f"위치 {stats['0']['n']}곳 (접두어 0/1/2글자), 후보 상위 {MAX_CANDS}개, 문맥 40줄\n")
    print("미리 선택된 항목이 정답인 비율 (R@1)")
    print("접두어 | " + " | ".join(f"{label[c]:^16}" for c in cols))
    for k in PREFIXES:
        st = stats[k]
        print(f"  {k}글자 | " + " | ".join(f"{pct(st[c]['r1'], st['n']):^16}" for c in cols))
    print("\nMRR")
    for k in PREFIXES:
        st = stats[k]
        print(f"  {k}글자 | " + " | ".join(f"{st[c]['rr'] / max(1, st['n']):^16.3f}" for c in cols))
    print("\n상위 5개 안에 정답 (R@5)")
    for k in PREFIXES:
        st = stats[k]
        print(f"  {k}글자 | " + " | ".join(f"{pct(st[c]['r5'], st['n']):^16}" for c in cols))
    print("\n위치 종류별 R@1, 0글자 (" + " / ".join(label[c] for c in cols) + ")")
    for kind in ("member", "scope", "ident"):
        bk = by_kind.get((kind, "0"))
        if bk:
            print(f"  {kind:6s} n={bk['n']:3d} | " + " / ".join(pct(bk[c], bk["n"]) for c in cols))

    q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] if xs else 0
    print(f"\n로컬 지연 (RTX 4080 SUPER, fp32 평가 경로): 학습 전 중앙값 {q(ms['base'], .5):.0f}ms / p90 {q(ms['base'], .9):.0f}ms, "
          f"학습 후 중앙값 {q(ms['ft'], .5):.0f}ms / p90 {q(ms['ft'], .9):.0f}ms")


if __name__ == "__main__":
    main()
