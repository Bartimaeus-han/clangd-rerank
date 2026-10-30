"""2단계 특징 랭커의 표준 라이브러리 전용 구현 (lightgbm·numpy 없이 프록시 안에서 돌리기 위한 것).

- features(cands, state, typed): stage1_ranker.features 와 같은 순서의 특징 행렬 (list of list)
- LGBModel(path).predict(rows): LightGBM 텍스트 모델(.txt) 파서 + 트리 평가기. 숫자 분기(decision_type 2)만 지원한다.
  stage1_ranker.py 로 만든 모델은 전부 숫자 분기라 lightgbm 결과와 같다 (test_stage2_lite.py 로 확인).
"""
import math
import re

KINDS = ["function", "method", "variable", "field", "class", "struct", "namespace", "keyword", "enum member",
         "constant", "property", "constructor", "interface", "enum", "value", "text", "snippet", "symbol"]
_IDENT = re.compile(r"[A-Za-z_]\w*")
_SUB = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def subtokens(name):
    return set(t.lower() for t in _SUB.findall(name.replace("_", " ")) if len(t) > 1)


def features(cands, state, typed):
    """cands: [{"name", "kind", "detail"}], state: 커서 앞 문맥 + '<CURSOR>', typed: 친 글자 수."""
    ctx = state.split("<CURSOR>")[0]
    lines = ctx.split("\n")
    cur_line, prev_lines = lines[-1], lines[:-1]
    counts = {}
    for w in _IDENT.findall("\n".join(prev_lines)):
        counts[w] = counts.get(w, 0) + 1
    last_seen = {}
    for i, l in enumerate(reversed(prev_lines)):
        for w in set(_IDENT.findall(l)):
            last_seen.setdefault(w, i + 1)
    cur_words = set(_IDENT.findall(cur_line))
    last_sub = set()
    for w in _IDENT.findall(" ".join(prev_lines[-2:]) + " " + cur_line):
        last_sub |= subtokens(w)
    n_cands = len(cands)
    rows = []
    for rank, c in enumerate(cands):
        n = c["name"]
        sub = subtokens(n)
        kind = c.get("kind", "symbol")
        detail = c.get("detail", "")
        overlap = len(sub & last_sub)
        rows.append([
            rank, 1.0 / (rank + 1), len(n), typed, n_cands,
            counts.get(n, 0), min(last_seen.get(n, 99), 99), float(n in cur_words),
            overlap, overlap / max(1, len(sub)),
            float(n[0].isupper()), float("_" in n), float(n.isupper() and len(n) > 2), float(n.startswith("_")),
            len(detail), detail.count("("),
            *[float(kind == kk) for kk in KINDS],
        ])
    return rows


class LGBModel:
    """LightGBM 텍스트 모델. 각 트리는 (split_feature, threshold, left_child, right_child, leaf_value, default_left)."""

    def __init__(self, path):
        self.trees = []
        block = {}
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("Tree="):
                block = {}
                self.trees.append(block)
            elif block is not None and "=" in line and self.trees:
                k, v = line.split("=", 1)
                if k in ("split_feature", "left_child", "right_child"):
                    block[k] = [int(x) for x in v.split()]
                elif k in ("threshold", "leaf_value"):
                    block[k] = [float(x) for x in v.split()]
                elif k == "decision_type":
                    block[k] = [int(x) for x in v.split()]
        self.trees = [t for t in self.trees if "split_feature" in t or "leaf_value" in t]
        for t in self.trees:
            if "split_feature" not in t:  # 잎 하나짜리 트리
                t["split_feature"] = []
            for d in t.get("decision_type", []):
                if d & 1:
                    raise ValueError("categorical split is not supported")
            t["default_left"] = [bool(d & 2) for d in t.get("decision_type", [])]

    def predict_one(self, x):
        s = 0.0
        for t in self.trees:
            sf, th, lc, rc, lv, dl = t["split_feature"], t["threshold"], t["left_child"], t["right_child"], t["leaf_value"], t["default_left"]
            if not sf:
                s += lv[0]
                continue
            node = 0
            while True:
                v = x[sf[node]]
                if v != v:  # NaN
                    go_left = dl[node]
                else:
                    go_left = v <= th[node]
                node = lc[node] if go_left else rc[node]
                if node < 0:
                    s += lv[-node - 1]
                    break
        return s

    def predict(self, rows):
        return [self.predict_one(r) for r in rows]


def order(model, cands, state, typed):
    """2단계 점수 내림차순 인덱스 (동점이면 원래 순서)."""
    scores = model.predict(features(cands, state, typed))
    return sorted(range(len(cands)), key=lambda i: (-scores[i], i))
