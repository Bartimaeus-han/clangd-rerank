#!/usr/bin/env python3
"""Kev 의 기반 모델(Qwen3.5-0.8B-Base)을 LM 헤드 그대로 써서 커서 다음 식별자를 생성하는 기준선 (파인튜닝 전).
사용: ext/kev/.venv/bin/python scripts/gen_qwen.py <dir> [--limit N] [--beams 5] [--ctx 40] [--model Qwen/Qwen3.5-0.8B-Base]
출력: <dir>/qwen-base-gen.jsonl  {"i","k","guesses":[...5],"ms"}  → gen_report.py / claude_eval.py genmatch 로 채점.
빔 탐색으로 상위 추측을 뽑는다. 접두어가 있는 자리는 토큰 경계 문제(접두어를 프롬프트 끝에 붙이면 "C"+"CLI" 처럼 망가짐)를 피하려고
접두어 없이 프롬프트를 주고, 생성 첫 토큰들이 접두어와 맞도록(prefix_allowed_tokens_fn) 제약한다. 키워드는 뺀다. 지연(ms)은 GPU 한 건 기준."""
import argparse, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_rerank import KEYWORDS  # noqa: E402
from ctx_enrich import build_prompt  # noqa: E402

IDENT = re.compile(r"^[A-Za-z_]\w*")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir"); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--beams", type=int, default=5)
    ap.add_argument("--ctx", type=int, default=40); ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B-Base")
    ap.add_argument("--new-tokens", type=int, default=8); ap.add_argument("--tag", default="qwen-base")
    ap.add_argument("--adapter", default="", help="peft LoRA 어댑터 폴더 (Namer 학습본)")
    ap.add_argument("--load-4bit", action="store_true", help="bitsandbytes NF4 4비트로 올린다 (7B 급을 16GB GPU 에)")
    ap.add_argument("--src-root", default="", help="샘플의 proj/file 이 있는 소스 루트 (파일 전체의 커서 앞부분을 읽는다)")
    ap.add_argument("--enrich", action="store_true", help="ctx_enrich.build_prompt: 앞선 선언 요약을 프롬프트 앞에 붙인다 (--src-root 필요)")
    a = ap.parse_args()
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.model)
    if a.load_4bit:
        from transformers import BitsAndBytesConfig
        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        lm = AutoModelForCausalLM.from_pretrained(a.model, quantization_config=q, device_map={"": 0})
    else:
        lm = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16)
    if a.adapter:
        from peft import PeftModel
        lm = PeftModel.from_pretrained(lm, a.adapter).merge_and_unload()
    lm = (lm if a.load_4bit else lm.cuda()).eval()
    vocab = [tok.decode([t]) for t in range(len(tok))]
    all_ids = list(range(len(tok)))
    allowed_cache = {}

    def allowed_for(rem):
        """남은 접두어 rem 과 맞물리는 토큰: 토큰(앞 공백 제거)이 rem 으로 시작하거나 rem 이 토큰으로 시작."""
        if rem not in allowed_cache:
            allowed_cache[rem] = [t for t, v in enumerate(vocab) if (w := v.lstrip(" ")) and (w.startswith(rem) or rem.startswith(w))] or all_ids
        return allowed_cache[rem]

    samples = [json.loads(l) for l in open(os.path.join(a.dir, "samples.jsonl"))]
    if a.limit:
        samples = samples[:a.limit]
    out = os.path.join(a.dir, f"{a.tag}-gen.jsonl")
    done = {(r["i"], r["k"]) for r in map(json.loads, open(out))} if os.path.exists(out) else set()
    n = 0
    with open(out, "a") as f, torch.inference_mode():
        for i, s in enumerate(samples):
            for k, lv in s["levels"].items():
                if (i, k) in done:
                    continue
                typed = s["gold"][:int(k)]
                before = lv["state"].split("<CURSOR>")[0]
                if typed:
                    before = before[:-len(typed)]
                if a.src_root:  # 파일 전체의 커서 앞부분 (state 는 마지막 수십 줄뿐)
                    path = os.path.join(a.src_root, s["proj"], s["file"])
                    try:
                        L = open(path, errors="ignore").read().split("\n")
                        before = "\n".join(L[:s["line"]] + [L[s["line"]][:s["col"]]])
                    except OSError:
                        pass
                prompt = build_prompt(before, a.ctx, a.enrich)

                ids = tok(prompt, return_tensors="pt").input_ids.cuda()
                n_in = ids.shape[1]

                def prefix_fn(batch_id, seq):
                    if not typed:
                        return all_ids
                    sofar = tok.decode(seq[n_in:], skip_special_tokens=True).lstrip(" ")
                    return all_ids if sofar.startswith(typed) else allowed_for(typed[len(sofar):] if typed.startswith(sofar) else typed)

                t0 = time.perf_counter()
                gen = lm.generate(ids, max_new_tokens=a.new_tokens, num_beams=a.beams, num_return_sequences=a.beams, do_sample=False,
                                  early_stopping=True, pad_token_id=tok.pad_token_id or tok.eos_token_id,
                                  prefix_allowed_tokens_fn=prefix_fn if typed else None)
                guesses, seen = [], set()
                for g in gen:
                    m = IDENT.match(tok.decode(g[n_in:], skip_special_tokens=True).lstrip())
                    if m and m.group(0).startswith(typed) and m.group(0) not in KEYWORDS and m.group(0) not in seen:
                        seen.add(m.group(0)); guesses.append(m.group(0))
                torch.cuda.synchronize()
                ms = (time.perf_counter() - t0) * 1000
                f.write(json.dumps({"i": i, "k": k, "guesses": guesses[:5], "ms": ms, "in_tok": n_in}) + "\n")
                n += 1
                if n % 500 == 0:
                    print(f"  {n}", flush=True)
    print(f"{n}건 → {out}")


if __name__ == "__main__":
    main()
