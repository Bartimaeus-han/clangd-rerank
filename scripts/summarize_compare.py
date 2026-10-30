"""compare-<태그>.txt / compare-<태그>-app.txt 여러 개를 읽어 모델별 R@1 비교표(마크다운)를 찍는다.
사용: summarize_compare.py <kev_data 폴더> <태그> [<태그> ...]   (예: v2e1 v3s3 v4)
"""
import os, re, sys

d, tags = sys.argv[1], sys.argv[2:]
SETS = ["val", "test_fmt", "test_lz4", "test_entt", "test_cxxopts", "app"]
NAME = {"val": "CLI11(검증)", "test_fmt": "fmt", "test_lz4": "lz4", "test_entt": "entt", "test_cxxopts": "cxxopts", "app": "응용(23저장소)"}


def parse(path, tag):
    """{set: {"n":int, "r1":{0:(clangd,kev,jev)}, "kind":{name:(n,clangd,kev,jev)}}}"""
    out, cur, hdr, mode = {}, None, None, None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"=+ \[(\w+)\]", line)
        if m:
            cur = m.group(1); out[cur] = {"r1": {}, "kind": {}}; mode = None; continue
        if cur is None:
            cur = "app"; out[cur] = {"r1": {}, "kind": {}}
        m = re.match(r"위치 (\d+)곳", line)
        if m:
            out[cur]["n"] = int(m.group(1)); continue
        if line.startswith("접두어"):
            hdr = [h.strip() for h in line.split("|")]; ki = hdr.index("Kev-0.8B 학습 후"); ji = hdr.index("Jev"); continue
        if line.startswith("미리 선택"): mode = "r1"; continue
        if line.startswith("MRR") or line.startswith("상위 5개"): mode = None; continue
        if line.startswith("위치 종류별"): mode = "kind"; continue
        if mode == "r1" and re.match(r"\s+[012]글자 \|", line):
            c = [x.strip() for x in line.split("|")]; p = int(c[0][0])
            out[cur]["r1"][p] = (c[1], c[ki], c[ji])
        elif mode == "kind" and re.match(r"\s+(member|scope|ident)", line):
            m = re.match(r"\s+(\w+)\s+n=\s*(\d+) \|(.*)", line); vals = [v.strip() for v in m.group(3).split("/")]
            out[cur]["kind"][m.group(1)] = (int(m.group(2)), vals[0], vals[ki - 1], vals[ji - 1])
    return out


data = {}
for t in tags:
    data[t] = parse(os.path.join(d, f"compare-{t}.txt"), t)
    ap = os.path.join(d, f"compare-{t}-app.txt")
    if os.path.exists(ap):
        data[t].update(parse(ap, t))
first = tags[0]
print("| 시험셋 | n | 접두어 | clangd | " + " | ".join(tags) + " | Jev |")
print("|---|---|---|---|" + "---|" * len(tags) + "---|")
tot = {t: [0.0, 0, 0] for t in tags}  # 라이브러리 5세트 0글자 n가중 합
for s in SETS:
    if s not in data[first]: continue
    n = data[first][s]["n"]
    for p in (0, 1, 2):
        row = data[first][s]["r1"][p]
        kevs = [data[t][s]["r1"][p][1] if s in data[t] else "-" for t in tags]
        print(f"| {NAME[s] if p == 0 else ''} | {n if p == 0 else ''} | {p}글자 | {row[0]} | " + " | ".join(kevs) + f" | {row[2]} |")
        if p == 0 and s != "app":
            for t in tags:
                if s in data[t]: tot[t][0] += n * float(data[t][s]["r1"][0][1].rstrip("%")); tot[t][1] += n
print("| 라이브러리 5세트 n가중 | " + str(tot[first][1]) + " | 0글자 | - | " + " | ".join(f"{tot[t][0]/tot[t][1]:.1f}%" for t in tags) + " | - |")
print()
print("위치 종류별 0글자 R@1 (clangd / " + " / ".join(tags) + " / Jev)")
print("| 시험셋 | 종류 | n | clangd | " + " | ".join(tags) + " | Jev |")
print("|---|---|---|---|" + "---|" * len(tags) + "---|")
for s in SETS:
    if s not in data[first]: continue
    for k in ("member", "scope", "ident"):
        if k not in data[first][s]["kind"]: continue
        kn, c, _, j = data[first][s]["kind"][k]
        kevs = [data[t][s]["kind"][k][2] if s in data[t] and k in data[t][s]["kind"] else "-" for t in tags]
        print(f"| {NAME[s]} | {k} | {kn} | {c} | " + " | ".join(kevs) + f" | {j} |")
