"""1단계 특징 기반 랭커: clangd 후보(최대 255개)를 가벼운 특징으로 다시 매겨, 정답이 상위 K개 안에 드는 비율(recall@K)을 올린다.

사용: stage1_ranker.py <train samples.jsonl ...> -- <val samples.jsonl ...>
LightGBM lambdarank. 특징은 프록시 안에서 ms 안에 계산할 수 있는 것만 쓴다:
  clangd 순위, 후보 종류, 이름 길이, 친 글자 수, 문맥(앞 40줄)에서의 등장 횟수·마지막 등장까지 거리·현재 줄 등장,
  마지막 줄 단어와의 서브토큰 겹침, 대문자/밑줄/매크로 모양, 시그니처 길이.
출력: 접두어별 recall@16/30/60, R@1 (clangd 순서 vs 랭커) 와 특징 중요도.
"""
import json, os, re, sys
import numpy as np
import lightgbm as lgb

KINDS = ["function", "method", "variable", "field", "class", "struct", "namespace", "keyword", "enum member",
         "constant", "property", "constructor", "interface", "enum", "value", "text", "snippet", "symbol"]


def subtokens(name):
    return set(t.lower() for t in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", name.replace("_", " ")) if len(t) > 1)


def features(sample, k):
    lv = sample["levels"][k]
    cands = lv["cands"]
    ctx = lv["state"].split("<CURSOR>")[0]
    lines = ctx.split("\n")
    cur_line, prev_lines = lines[-1], lines[:-1]
    words_ctx = re.findall(r"[A-Za-z_]\w*", "\n".join(prev_lines))
    counts = {}
    for w in words_ctx:
        counts[w] = counts.get(w, 0) + 1
    last_seen = {}
    for i, l in enumerate(reversed(prev_lines)):  # i = 몇 줄 전
        for w in set(re.findall(r"[A-Za-z_]\w*", l)):
            last_seen.setdefault(w, i + 1)
    cur_words = set(re.findall(r"[A-Za-z_]\w*", cur_line))
    last_sub = set()
    for w in re.findall(r"[A-Za-z_]\w*", " ".join(prev_lines[-2:]) + " " + cur_line):
        last_sub |= subtokens(w)
    typed = int(k)
    rows, labels = [], []
    for rank, c in enumerate(cands):
        n = c["name"]
        sub = subtokens(n)
        kind = c.get("kind", "symbol")
        rows.append([
            rank, 1.0 / (rank + 1), len(n), typed, len(cands),
            counts.get(n, 0), min(last_seen.get(n, 99), 99), n in cur_words,
            len(sub & last_sub), len(sub & last_sub) / max(1, len(sub)),
            n[0].isupper(), "_" in n, n.isupper() and len(n) > 2, n.startswith("_"),
            len(c.get("detail", "")), c.get("detail", "").count("("),
            *[kind == kk for kk in KINDS],
        ])
        labels.append(1 if n == sample["gold"] else 0)
    return np.array(rows, dtype=np.float32), np.array(labels), lv


FEATURE_NAMES = ["clangd_rank", "clangd_rank_inv", "name_len", "typed", "n_cands", "ctx_count", "lines_since", "in_cur_line",
                 "subtok_overlap", "subtok_frac", "upper_first", "has_underscore", "macro_like", "underscore_first",
                 "detail_len", "detail_parens"] + [f"kind_{k}" for k in KINDS]


def build(paths):
    X, y, groups, meta = [], [], [], []
    for p in paths:
        for l in open(p):
            s = json.loads(l)
            for k in ("0", "1", "2"):
                if k not in s["levels"]:
                    continue
                f, lab, lv = features(s, k)
                if lab.sum() == 0:
                    continue
                X.append(f); y.append(lab); groups.append(len(lab)); meta.append(k)
    return np.vstack(X), np.concatenate(y), groups, meta


def evaluate(y, groups, meta, scores):
    out = {}
    pos = 0
    for g, k in zip(groups, meta):
        lab, sc = y[pos:pos + g], scores[pos:pos + g]
        pos += g
        gold = int(np.argmax(lab))
        # 동점이면 원래(clangd) 순서 유지: 안정 정렬
        order = np.argsort(-sc, kind="stable")
        rank = int(np.where(order == gold)[0][0]) + 1
        d = out.setdefault(k, {"n": 0, "r1": 0, "r16": 0, "r30": 0, "r60": 0, "rr": 0.0})
        d["n"] += 1; d["r1"] += rank == 1; d["r16"] += rank <= 16; d["r30"] += rank <= 30; d["r60"] += rank <= 60; d["rr"] += 1 / rank
    return out


def show(title, res):
    print(f"\n{title}")
    print("접두어 |  n  |  R@1  | recall@16 | recall@30 | recall@60 |  MRR")
    for k in ("0", "1", "2"):
        d = res[k]; n = d["n"]
        print(f"  {k}글자 | {n:3d} | {100*d['r1']/n:5.1f}% |   {100*d['r16']/n:5.1f}%  |   {100*d['r30']/n:5.1f}%  |   {100*d['r60']/n:5.1f}%  | {d['rr']/n:.3f}")


def main():
    i = sys.argv.index("--")
    train_paths, val_paths = sys.argv[1:i], sys.argv[i + 1:]
    Xt, yt, gt, _ = build(train_paths)
    vals = [(p, *build([p])) for p in val_paths]  # 첫 번째 검증셋으로 조기 종료, 나머지는 보고만
    Xv, yv, gv, mv = vals[0][1:]
    print(f"학습 질의 {len(gt)}개 ({len(yt)}행), 검증 질의 {len(gv)}개 ({len(yv)}행)")
    model = lgb.LGBMRanker(objective="lambdarank", n_estimators=400, learning_rate=0.05, num_leaves=31,
                           min_child_samples=20, subsample=0.8, colsample_bytree=0.8, verbose=-1,
                           lambdarank_truncation_level=60)
    model.fit(Xt, yt, group=gt, eval_set=[(Xv, yv)], eval_group=[gv], eval_at=[1, 16, 60],
              callbacks=[lgb.early_stopping(40, verbose=False)])
    for p, X, y, g, m in vals:
        name = p.split("/")[-2]
        show(f"[{name}] clangd 기본 순서", evaluate(y, g, m, -X[:, 0]))
        show(f"[{name}] LightGBM 2단계 랭커 ({model.best_iteration_}트리)", evaluate(y, g, m, model.predict(X)))
    imp = sorted(zip(model.feature_importances_, FEATURE_NAMES), reverse=True)[:12]
    print("\n특징 중요도 상위:", ", ".join(f"{n}={v}" for v, n in imp))
    out = os.environ.get("STAGE2_OUT", "stage2_lgb.txt")
    model.booster_.save_model(out)
    print("모델 저장:", out)


if __name__ == "__main__":
    main()
