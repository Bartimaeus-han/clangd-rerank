"""stage2_lite 가 lightgbm + stage1_ranker.features 와 같은 점수를 내는지, 그리고 얼마나 빠른지."""
import json, sys, time
import numpy as np, lightgbm as lgb
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from stage1_ranker import features as ref_features
import stage2_lite

model_path, samples = sys.argv[1:3]
ref = lgb.Booster(model_file=model_path)
lite = stage2_lite.LGBModel(model_path)
print("트리 수:", len(lite.trees), ref.num_trees())
maxdiff = 0.0; n = 0; t_lite = 0.0; big = None
for line in open(samples):
    s = json.loads(line)
    for k in ("0", "1", "2"):
        lv = s["levels"][k]
        X, _, _ = ref_features(s, k)
        a = ref.predict(X)
        t0 = time.perf_counter()
        b = lite.predict(stage2_lite.features(lv["cands"], lv["state"], int(k)))
        t_lite += time.perf_counter() - t0
        maxdiff = max(maxdiff, float(np.max(np.abs(a - np.array(b)))))
        n += 1
        if big is None or len(lv["cands"]) > big[0]:
            big = (len(lv["cands"]), lv)
    if n >= 300: break
print(f"질의 {n}개, 점수 최대 차이 {maxdiff:.2e}, lite 평균 {1000*t_lite/n:.1f}ms/질의")
t0 = time.perf_counter()
for _ in range(10):
    stage2_lite.order(lite, big[1]["cands"], big[1]["state"], 0)
print(f"후보 {big[0]}개 질의: {100*(time.perf_counter()-t0):.1f}ms (특징+예측+정렬)")
