#!/usr/bin/env python3
"""Namer 학습: Qwen3.5-0.8B-Base 에 LoRA 를 붙여 '커서 앞 코드 → 선언 이름' 을 배운다 (HF transformers + peft).
사용: ext/kev/.venv/bin/python scripts/train_namer.py <namer_raw.jsonl> <출력 폴더> [--max-train 60000] [--val-repos 10] [--lr 1e-4] [--epochs 1]
  학습 예: 프롬프트 = prefix 의 마지막 --ctx 줄(기본 40, 서버와 같음; 끝이 보통 공백), 정답 = 이름 토큰 + EOS. 손실은 정답 토큰에만.
  토큰화는 서버(gen_server.py)와 똑같이 프롬프트와 이름을 따로 토큰화해 이어 붙인다(공백 경계가 어긋나지 않게).
  검증: 저장소 --val-repos 개를 통째로 떼어 손실과 greedy exact@1 을 잰다 (일반화 확인). 진짜 시험은 eval_gen_fresh 로 gen_qwen.py --adapter.
출력: <출력 폴더>/ (peft 어댑터) + train_log.jsonl. gen_server.py --adapter <출력 폴더> 로 서빙."""
import argparse, collections, json, math, os, random, re, sys, time

IDENT = re.compile(r"^[A-Za-z_]\w*")


def build(samples, tok, ctx, max_len):
    """(input_ids, labels) 목록. labels 는 프롬프트 구간 -100."""
    out = []
    eos = tok.eos_token_id
    for s in samples:
        prompt = "\n".join(s["prefix"].split("\n")[-ctx:])
        p_ids = tok(prompt).input_ids
        n_ids = tok(s["gold"]).input_ids + [eos]
        if len(p_ids) + len(n_ids) > max_len:
            p_ids = p_ids[-(max_len - len(n_ids)):]
        out.append((p_ids + n_ids, [-100] * len(p_ids) + n_ids))
    return out


def batches(data, bs, pad, shuffle, rng):
    idx = list(range(len(data)))
    if shuffle:
        rng.shuffle(idx)
        # 길이가 비슷한 것끼리 묶어 패딩 낭비를 줄인다 (덩어리 단위 셔플)
        chunks = [sorted(idx[i:i + bs * 50], key=lambda j: len(data[j][0])) for i in range(0, len(idx), bs * 50)]
        idx = [j for c in chunks for j in c]
        groups = [idx[i:i + bs] for i in range(0, len(idx), bs)]
        rng.shuffle(groups)
    else:
        groups = [idx[i:i + bs] for i in range(0, len(idx), bs)]
    import torch
    for g in groups:
        # 왼쪽 패딩: 모든 행의 정답(이름) 토큰이 끝에 모이게 → 끝 K 자리의 로짓만 계산하면 된다 (어휘가 커서 전체 로짓은 메모리 폭발)
        L = max(len(data[j][0]) for j in g)
        K = max(sum(x != -100 for x in data[j][1]) for j in g)
        ids = torch.full((len(g), L), pad, dtype=torch.long); lab = torch.full((len(g), L), -100, dtype=torch.long)
        att = torch.zeros((len(g), L), dtype=torch.long)
        for r, j in enumerate(g):
            a, b = data[j]
            ids[r, L - len(a):] = torch.tensor(a); lab[r, L - len(b):] = torch.tensor(b); att[r, L - len(a):] = 1
        yield ids, att, lab, K


def tail_loss(model, ids, att, lab, K):
    """끝 K 토큰(이름+EOS)에 대한 교차 엔트로피. logits_to_keep 으로 마지막 K+1 자리만 로짓을 만든다."""
    import torch, torch.nn.functional as F
    pos = (att.cumsum(1) - 1).clamp(min=0)
    out = model(input_ids=ids, attention_mask=att, position_ids=pos, logits_to_keep=K + 1)
    logits = out.logits[:, :-1, :].float()  # 위치 L-K-1..L-2 의 로짓 → 토큰 L-K..L-1 예측
    tgt = lab[:, -K:]
    return F.cross_entropy(logits.reshape(-1, logits.shape[-1]), tgt.reshape(-1), ignore_index=-100), int((tgt != -100).sum())


@__import__("torch").no_grad()
def exact1(model, tok, samples, ctx, n=400):
    """greedy 로 이름을 만들어 정답과 비교 (0글자 자리)."""
    import torch
    hit = 0
    model.eval()
    for s in samples[:n]:
        prompt = "\n".join(s["prefix"].split("\n")[-ctx:])
        ids = tok(prompt, return_tensors="pt").input_ids[:, -1500:].cuda()
        g = model.generate(ids, max_new_tokens=8, do_sample=False, pad_token_id=tok.pad_token_id or tok.eos_token_id)
        m = IDENT.match(tok.decode(g[0, ids.shape[1]:], skip_special_tokens=True).lstrip())
        hit += bool(m) and m.group(0) == s["gold"]
    model.train()
    return hit / min(n, len(samples))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("out")
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B-Base"); ap.add_argument("--max-train", type=int, default=60000)
    ap.add_argument("--val-repos", type=int, default=10); ap.add_argument("--ctx", type=int, default=40); ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-4); ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--bs", type=int, default=8); ap.add_argument("--accum", type=int, default=2)
    ap.add_argument("--rank", type=int, default=16); ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--eval-every", type=int, default=1000); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    rng = random.Random(a.seed); torch.manual_seed(a.seed)
    os.makedirs(a.out, exist_ok=True)
    logf = open(os.path.join(a.out, "train_log.jsonl"), "a")

    rows = [json.loads(l) for l in open(a.data)]
    repos = sorted({r["src"] for r in rows}); rng.shuffle(repos)
    val_repos = set(repos[:a.val_repos])
    val = [r for r in rows if r["src"] in val_repos]; train = [r for r in rows if r["src"] not in val_repos]
    rng.shuffle(train); train = train[:a.max_train]; rng.shuffle(val); val = val[:2000]
    print(f"학습 {len(train)}건 ({len(repos) - len(val_repos)} 저장소), 검증 {len(val)}건 ({len(val_repos)} 저장소: {sorted(val_repos)})", flush=True)
    kinds = collections.Counter(r["kind"] for r in train); print("종류별", dict(kinds), flush=True)

    tok = AutoTokenizer.from_pretrained(a.model)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    model = AutoModelForCausalLM.from_pretrained(a.model, dtype=torch.bfloat16).cuda()
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    cfg = LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()  # LoRA 가중치는 fp32 로 (옵티마이저 안정)
    model.print_trainable_parameters()

    tr = build(train, tok, a.ctx, a.max_len); va = build(val, tok, a.ctx, a.max_len)
    print(f"토큰 길이 중앙값 {sorted(len(x[0]) for x in tr)[len(tr) // 2]}", flush=True)
    steps_total = math.ceil(len(tr) / a.bs / a.accum * a.epochs)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0, betas=(0.9, 0.99))
    warm = max(1, int(steps_total * 0.03))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / steps_total))))

    def val_loss():
        model.eval(); tot, n = 0.0, 0
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            for ids, att, lab, K in batches(va, a.bs, pad, False, rng):
                loss, k = tail_loss(model, ids.cuda(), att.cuda(), lab.cuda(), K)
                tot += float(loss) * k; n += k
        model.train(); return tot / max(1, n)

    model.train(); step, micro, t0, run = 0, 0, time.time(), 0.0
    base = {"step": 0, "val_loss": val_loss(), "exact1": exact1(model, tok, val, a.ctx)}
    print("학습 전", base, flush=True); logf.write(json.dumps(base) + "\n"); logf.flush()
    ep = 0
    while step < steps_total:
        for ids, att, lab, K in batches(tr, a.bs, pad, True, random.Random(a.seed + ep)):
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = tail_loss(model, ids.cuda(), att.cuda(), lab.cuda(), K)[0] / a.accum
            loss.backward(); run += float(loss); micro += 1
            if micro % a.accum:
                continue
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
            if step % 50 == 0:
                el = time.time() - t0
                print(f"step {step}/{steps_total} loss {run / 50:.3f} lr {sched.get_last_lr()[0]:.2e} {el / 60:.1f}분 남음≈{el / step * (steps_total - step) / 60:.0f}분", flush=True)
                logf.write(json.dumps({"step": step, "loss": run / 50}) + "\n"); logf.flush(); run = 0.0
            if step % a.eval_every == 0 or step == steps_total:
                rec = {"step": step, "val_loss": val_loss(), "exact1": exact1(model, tok, val, a.ctx)}
                print("검증", rec, flush=True); logf.write(json.dumps(rec) + "\n"); logf.flush()
                model.save_pretrained(a.out)
            if step >= steps_total:
                break
        ep += 1
    model.save_pretrained(a.out)
    print("저장:", a.out, flush=True)


if __name__ == "__main__":
    main()
