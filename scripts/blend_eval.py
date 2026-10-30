"""2단계(LightGBM) 점수와 3단계(Kev) 확률을 섞으면 나아지는지, 특히 scope 위치에서. CPU만 쓴다.
사용: blend_eval.py <stage2 model> <samples.jsonl> <pred.jsonl>   (pred 는 clangd 상위 60 세트에 대한 kev_local_eval 출력)
점수 = log p_kev + a * (2단계 점수 - 최대값)  ; a 를 훑는다. 2단계 특징은 (1) 전체 앞 문맥 (2) 40줄만 두 가지로 계산해 비교.
"""
import json, math, sys, collections
import numpy as np, lightgbm as lgb
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from stage1_ranker import features

model, samples_p, pred_p = sys.argv[1:4]
B = lgb.Booster(model_file=model)
S = [json.loads(l) for l in open(samples_p)]
P = {}
for l in open(pred_p):
    r = json.loads(l); P[r["i"]] = r
idx = [(s, k) for s in S for k in ("0", "1", "2") if s["gold"] in [c["name"] for c in s["levels"][k]["cands"][:60]]]

def cut40(state):
    pre, cur = state.split("<CURSOR>")[0].rsplit("\n", 1) if "\n" in state.split("<CURSOR>")[0] else ("", state.split("<CURSOR>")[0])
    return "\n".join(pre.split("\n")[-39:] + [cur + "<CURSOR>"])

rows = []  # (k, kind, gold, names, logp, s2_full, s2_40)
for i, (s, k) in enumerate(idx):
    r = P.get(i)
    if not r or r["probs"] is None: continue
    lv = s["levels"][k]; cands = lv["cands"][:60]; names = [c["name"] for c in cands]
    logp = np.array([math.log(max(r["probs"].get(n, 0.0), 1e-6)) for n in names])
    s_full = B.predict(features({"levels": {k: {"cands": cands, "state": lv["state"]}}, "gold": ""}, k)[0])
    s_40 = B.predict(features({"levels": {k: {"cands": cands, "state": cut40(lv["state"])}}, "gold": ""}, k)[0])
    rows.append((k, s.get("kind", "ident"), names.index(s["gold"]), logp, s_full - s_full.max(), s_40 - s_40.max()))

def r1(a, which, k="0", kind=None):
    n = h = 0
    for kk, kd, g, logp, sf, s4 in rows:
        if kk != k or (kind and kd != kind): continue
        sc = logp + a * (sf if which == "full" else s4)
        n += 1; h += int(np.argmax(sc)) == g
    return f"{100*h/max(1,n):5.1f}%({n})"

print("평균 앞 문맥 줄 수:", int(np.mean([s["levels"]["0"]["state"].split("<CURSOR>")[0].count("\n") for s in S])))
print("a      | 0글자 전체(full/40) | scope(full/40) | member(full/40) | ident(full/40) | 1글자 full | 2글자 full")
for a in (0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5):
    print(f"{a:<6} | {r1(a,'full')} {r1(a,'40')} | {r1(a,'full',kind='scope')} {r1(a,'40',kind='scope')} | {r1(a,'full',kind='member')} {r1(a,'40',kind='member')} | {r1(a,'full',kind='ident')} {r1(a,'40',kind='ident')} | {r1(a,'full','1')} | {r1(a,'full','2')}")
