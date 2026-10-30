"""2단계(LightGBM) 점수로 clangd 후보를 다시 정렬한 샘플 파일을 만든다. 3단계 입력 비교용.

사용: stage2_reorder.py <stage1_lgb.txt> <in samples.jsonl> <out samples.jsonl> [K=60]
위치 단위로 정답이 세 접두어 모두 상위 K 안에 있는 것만 남기고(eval_*60 과 같은 규칙), 후보를 상위 K개, 문맥을 40줄로 자른다.
"""
import json, os, sys
import lightgbm as lgb
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_ranker import features  # noqa: E402


def main():
    model_path, src, dst = sys.argv[1:4]
    K = int(sys.argv[4]) if len(sys.argv) > 4 else 60
    booster = lgb.Booster(model_file=model_path)
    kept = total = 0
    with open(dst, "w") as out:
        for line in open(src):
            s = json.loads(line)
            total += 1
            new_levels = {}
            for k, lv in s["levels"].items():
                X, _, _ = features(s, k)
                order = np.argsort(-booster.predict(X), kind="stable")
                cands = [lv["cands"][i] for i in order][:K]
                if s["gold"] not in [c["name"] for c in cands]:
                    new_levels = None
                    break
                pre = lv["state"].split("<CURSOR>")[0].split("\n")
                new_levels[k] = {**lv, "cands": cands, "state": "\n".join(pre[-40:]) + "<CURSOR>"}
            if new_levels:
                s["levels"] = new_levels
                out.write(json.dumps(s) + "\n")
                kept += 1
    print(f"{dst}: {kept}/{total}곳 (세 접두어 모두 2단계 상위 {K} 안에 정답)")


if __name__ == "__main__":
    main()
