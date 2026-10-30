"""F 단계 보고: 프로젝트별로 '전체 위치 기준' 정답률을 비교한다.

사용: stage_f_report.py <태그>
변형: clangd만 / clangd60+Kev / 2단계K60만 / 2단계K60+Kev / 2단계K30+Kev / 규칙(0~1글자: 2단계K60+Kev, 2글자: 2단계만)
'다루는 위치'는 그 변형의 후보 안에 정답이 있는 위치, '전체'는 못 다루는 위치를 오답으로 쳐서 전체 위치로 나눈 값.
"""
import json, os, sys

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = sys.argv[1]
PROJ = {  # 이름: (전체 샘플, clangd60 샘플 폴더, kev jsonl 이름)
    "CLI11": ("train_out/CLI11/samples.jsonl", "train_out/CLI11", "val", "cli"),  # val.jsonl 은 319곳 전체에서 만들었음
    "fmt": ("eval_noafter/samples.jsonl", "eval_fmt60", "test_fmt", "fmt"),
    "lz4": ("train_out2/lz4/samples.jsonl", "eval_lz460", "test_lz4", "lz4"),
    "entt": ("train_out2/entt/samples.jsonl", "eval_entt60", "test_entt", "entt"),
    "cxxopts": ("train_out2/cxxopts/samples.jsonl", "eval_cxxopts60", "test_cxxopts", "cxxopts"),
}
KS = ("0", "1", "2")


def load(p):
    return [json.loads(l) for l in open(os.path.join(S, p))]


def preds(p):
    out = {}
    p = os.path.join(S, p)
    if os.path.exists(p):
        for l in open(p):
            r = json.loads(l)
            out[r["i"]] = r
    return out


def hits_kev(samples, pred, K):
    """(sample,k) 인덱스를 to_kev_jsonl 규칙으로 되돌려 Kev 상위1 정답 수와 다루는 수를 접두어별로 센다."""
    h = {k: [0, 0] for k in KS}
    i = 0
    for s in samples:
        for k in KS:
            names = [c["name"] for c in s["levels"][k]["cands"][:K]]
            if s["gold"] not in names:
                continue
            r = pred.get(i)
            i += 1
            if not r or r["probs"] is None:
                continue
            top = max(names, key=lambda n: (r["probs"].get(n, 0.0), -names.index(n)))
            h[k][1] += 1
            h[k][0] += top == s["gold"]
    return h


def hits_top1(samples, K):
    h = {k: [0, 0] for k in KS}
    for s in samples:
        for k in KS:
            names = [c["name"] for c in s["levels"][k]["cands"][:K]]
            if s["gold"] in names:
                h[k][1] += 1
                h[k][0] += names[0] == s["gold"]
    return h


def main():
    for name, (full, d60, kev60, short) in PROJ.items():
        N = len(load(full))
        rows = {
            "clangd 그대로": hits_top1(load(full), 255),
            "clangd60 + Kev": hits_kev(load(f"{d60}/samples.jsonl"), preds(f"kev_data/pred-{TAG}-{kev60}.jsonl"), 60),
            "2단계K60 만": hits_top1(load(f"eval_{short}_s2k60/samples.jsonl"), 60),
            "2단계K60 + Kev": hits_kev(load(f"eval_{short}_s2k60/samples.jsonl"), preds(f"kev_data/pred-{TAG}-s2k60_{short}.jsonl"), 60),
            "2단계K30 + Kev": hits_kev(load(f"eval_{short}_s2k30/samples.jsonl"), preds(f"kev_data/pred-{TAG}-s2k30_{short}.jsonl"), 30),
        }
        rule = {k: rows["2단계K60 + Kev"][k] if k != "2" else rows["2단계K60 만"][k] for k in KS}
        rows["규칙(2글자부터 2단계만)"] = rule
        print(f"\n[{name}] 전체 위치 {N}곳 — 접두어별 '다루는 위치 R@1 (전체 기준 정답률)'")
        print(f"{'변형':<22}" + "".join(f"{k+'글자':>22}" for k in KS))
        for label, h in rows.items():
            cells = []
            for k in KS:
                hit, cov = h[k]
                cells.append(f"{100*hit/max(1,cov):5.1f}% ({100*hit/N:5.1f}%) n={cov:3d}" if cov else "      -      ")
            print(f"{label:<22}" + "".join(f"{c:>22}" for c in cells))


if __name__ == "__main__":
    main()
