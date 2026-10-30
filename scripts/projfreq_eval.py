"""프로젝트 전체 파일의 식별자 빈도(현재 파일 제외)를 사전 확률로 섞으면 Kev 결과가 나아지는지. CPU만.
사용: projfreq_eval.py <project_src_dir> <samples.jsonl> <pred.jsonl>
점수 = log p_kev + b * log(1 + 프로젝트 빈도)  (b 훑기), 종류별 0글자 R@1.
"""
import json, math, os, re, sys, collections
import numpy as np

src, samples_p, pred_p = sys.argv[1:4]
# 파일별 식별자 카운터
per_file = {}
for root, _, files in os.walk(src):
    if "/." in root or "/build" in root: continue
    for f in files:
        if f.endswith((".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh", ".ipp")):
            p = os.path.join(root, f)
            try: txt = open(p, errors="ignore").read()
            except OSError: continue
            per_file[os.path.realpath(p)] = collections.Counter(re.findall(r"[A-Za-z_]\w*", txt))
total = collections.Counter()
for c in per_file.values(): total.update(c)
print(f"프로젝트 파일 {len(per_file)}개, 식별자 토큰 {sum(total.values()):,}개")

S = [json.loads(l) for l in open(samples_p)]
P = {}
for l in open(pred_p):
    r = json.loads(l); P[r["i"]] = r
idx = [(s, k) for s in S for k in ("0", "1", "2") if s["gold"] in [c["name"] for c in s["levels"][k]["cands"][:60]]]
rows = []
for i, (s, k) in enumerate(idx):
    r = P.get(i)
    if not r or r["probs"] is None: continue
    names = [c["name"] for c in s["levels"][k]["cands"][:60]]
    own = per_file.get(os.path.realpath(s["file"]), collections.Counter())
    freq = np.array([math.log1p(max(0, total[n] - own[n])) for n in names])  # 현재 파일 제외
    logp = np.array([math.log(max(r["probs"].get(n, 0.0), 1e-6)) for n in names])
    rows.append((k, s.get("kind", "ident"), names.index(s["gold"]), logp, freq))

def r1(b, k="0", kind=None):
    n = h = 0
    for kk, kd, g, logp, fq in rows:
        if kk != k or (kind and kd != kind): continue
        n += 1; h += int(np.argmax(logp + b * fq)) == g
    return f"{100*h/max(1,n):5.1f}%({n})"
print("b     | 0글자 전체 | scope | member | ident | 1글자 | 2글자")
for b in (0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0):
    print(f"{b:<5} | {r1(b)} | {r1(b,kind='scope')} | {r1(b,kind='member')} | {r1(b,kind='ident')} | {r1(b,'1')} | {r1(b,'2')}")
