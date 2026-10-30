"""하이퍼파라미터 탐색: 설정마다 1 epoch 학습 -> CLI11 검증 -> 결과를 TSV에 적는다.

Kev venv의 파이썬으로, Kev 저장소 루트에서 실행: PYTHONPATH=. .venv/bin/python <이 파일> <sweep_dir> [설정이름 ...]
설정 이름을 안 주면 CONFIGS 전부를 순서대로 돈다. 이미 results.tsv에 있는 설정은 건너뛴다.
데이터 형식(문맥 줄 수, 후보 수)이 다른 설정은 to_kev_jsonl.py 로 학습·검증 파일을 따로 만든다.
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.dirname(HERE)
TRAIN_SRC = [f"{SCRATCH}/train_out/{p}/samples.jsonl" for p in ("lua", "zstd", "tinyxml2", "abseil", "spdlog", "json", "glm")]
VAL_SRC = [f"{SCRATCH}/train_out/CLI11/samples.jsonl"]
BASE = "Qwen/Qwen3.5-0.8B-Base"
INIT = "jaredpalmer/kev-0.8b"
COMMON = ["--base", BASE, "--epochs", "1", "--batch", "1", "--accum", "8", "--dtype", "bf16", "--checkpointing", "1",
          "--max_state", "1400", "--p_none", "0", "--p_none_distract", "0", "--p_distract", "0", "--device", "cuda"]

# 이름: (학습 인자, 문맥 줄 수, 후보 수)
CONFIGS = {
    "lr2e-5":        (["--lr", "2e-5"], 40, 60),   # 1차 학습과 같은 설정, 1 epoch
    "lr1e-5":        (["--lr", "1e-5"], 40, 60),
    "lr5e-5":        (["--lr", "5e-5"], 40, 60),
    "head2e-4":      (["--lr", "2e-5", "--head_lr", "2e-4"], 40, 60),
    "smooth0.1":     (["--lr", "2e-5", "--label_smoothing", "0.1"], 40, 60),
    "ctx20":         (["--lr", "2e-5"], 20, 60),
    "ctx80":         (["--lr", "2e-5"], 80, 60),
    "cands30":       (["--lr", "2e-5"], 40, 30),
    "cands100":      (["--lr", "2e-5"], 40, 100),
}


def data_files(sweep_dir, ctx, cands):
    """형식별 학습·검증 JSONL. 없으면 만든다."""
    tag = f"ctx{ctx}_c{cands}"
    tr, va = f"{sweep_dir}/data/train_{tag}.jsonl", f"{sweep_dir}/data/val_{tag}.jsonl"
    os.makedirs(f"{sweep_dir}/data", exist_ok=True)
    env = {**os.environ, "CTX_LINES": str(ctx), "MAX_CANDS": str(cands)}
    for out, src in ((tr, TRAIN_SRC), (va, VAL_SRC)):
        if not os.path.exists(out):
            subprocess.run([sys.executable, "-I", f"{HERE}/to_kev_jsonl.py", out, *src], env=env, check=True, capture_output=True)
    return tr, va


def metrics(val_src, val_jsonl, pred_jsonl, cands):
    """0글자 R@1, 전체 R@1, 전체 MRR. to_kev_jsonl.py 와 같은 규칙으로 pred i 를 (위치, 접두어)에 되돌린다."""
    samples = [json.loads(l) for l in open(val_src[0])]
    index = [(s, k) for s in samples for k in ("0", "1", "2")
             if s["gold"] in [c["name"] for c in s["levels"][k]["cands"][:cands]]]
    assert len(index) == sum(1 for _ in open(val_jsonl))
    preds = {}
    for l in open(pred_jsonl):
        r = json.loads(l)
        preds[r["i"]] = r
    n = r1 = n0 = r1_0 = 0
    rr = 0.0
    ms = []
    for i, (s, k) in enumerate(index):
        p = preds.get(i)
        if not p or p["probs"] is None:
            continue
        names = [c["name"] for c in s["levels"][k]["cands"][:cands]]
        rank = sorted(names, key=lambda x: (-p["probs"].get(x, 0), names.index(x))).index(s["gold"]) + 1
        n += 1; r1 += rank == 1; rr += 1 / rank; ms.append(p["ms"])
        if k == "0":
            n0 += 1; r1_0 += rank == 1
    ms.sort()
    return {"n": n, "r1_0": r1_0 / max(1, n0), "r1_all": r1 / max(1, n), "mrr": rr / max(1, n), "ms_p50": ms[len(ms) // 2] if ms else 0}


def main():
    sweep_dir = os.path.abspath(sys.argv[1])
    names = sys.argv[2:] or list(CONFIGS)
    results = f"{sweep_dir}/results.tsv"
    os.makedirs(sweep_dir, exist_ok=True)
    done = set()
    if os.path.exists(results):
        done = {l.split("\t")[0] for l in open(results)}
    else:
        with open(results, "w") as f:
            f.write("config\tctx\tcands\tn_val\tr1_0char\tr1_all\tmrr\tms_p50\ttrain_min\n")
    for name in names:
        if name in done:
            print(f"== {name}: 이미 있음, 건너뜀", flush=True)
            continue
        args, ctx, cands = CONFIGS[name]
        tr, va = data_files(sweep_dir, ctx, cands)
        out = f"{sweep_dir}/runs/{name}"
        print(f"== {name}: 학습 시작 ({ctx}줄, 후보 {cands})", flush=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, "-m", "kev.train", "--data", tr, "--init_from", INIT, "--out", out, *COMMON, *args],
                           capture_output=True, text=True)
        train_min = (time.time() - t0) / 60
        if r.returncode:
            print(f"   학습 실패: {r.stderr[-300:]}", flush=True)
            continue
        pred = f"{sweep_dir}/runs/{name}-val.jsonl"
        r = subprocess.run([sys.executable, f"{HERE}/kev_local_eval.py", out, va, pred], capture_output=True, text=True)
        if r.returncode:
            print(f"   평가 실패: {r.stderr[-300:]}", flush=True)
            continue
        m = metrics(VAL_SRC, va, pred, cands)
        with open(results, "a") as f:
            f.write(f"{name}\t{ctx}\t{cands}\t{m['n']}\t{m['r1_0']:.3f}\t{m['r1_all']:.3f}\t{m['mrr']:.3f}\t{m['ms_p50']:.0f}\t{train_min:.0f}\n")
        print(f"   0글자 R@1 {100 * m['r1_0']:.1f}%  전체 R@1 {100 * m['r1_all']:.1f}%  MRR {m['mrr']:.3f}  ({train_min:.0f}분)", flush=True)


if __name__ == "__main__":
    main()
