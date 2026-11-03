#!/usr/bin/env python3
"""Claude API 실험: (1) clangd 후보 재정렬, (2) 후보 없이 식별자 생성. jevenv 파이썬으로 실행 (anthropic SDK 설치됨).

사용 (프로젝트 루트에서, 보통은 scripts/run_claude.sh 를 통해):
  claude_eval.py rerank   <dir> [--model M] [--effort low] [--workers 8] [--limit N] [--ctx 40] [--dry-run] [--count-tokens]
  claude_eval.py generate <dir> [같은 옵션]
  claude_eval.py batch-submit rerank|generate <dir> [--model M ...]     Message Batches (50% 가격, 보통 1시간 안에 끝남)
  claude_eval.py batch-fetch  rerank|generate <dir> [--model M]         끝났으면 결과를 받아 같은 출력 파일을 만든다
  claude_eval.py genmatch <dir> [--model M]   <model>-gen.jsonl 의 추측을 clangd 후보에 대응시켜 재정렬 파일 <model>-genmatch.jsonl 로
      (후보에 있는 추측을 순서대로 맨 위에, 없으면 clangd 순서 그대로). 후보 목록 없이 생성만 시키는 편이 싸고 정확했다(CLI11 Haiku).
  claude_eval.py compare <dir> [--files a.jsonl,b.jsonl] [--ref "Kev v4=73.7/89.1/93.6"]
      clangd + 재정렬 결과 파일들(기본: jev.jsonl 과 <dir>/claude-*.jsonl 전부)을 같은 위치 집합에서 비교.
      R@1/MRR/R@5, 종류별 R@1, 오류 수, 지연, 실제 토큰 사용량과 비용(정가, 배치는 절반), 1,000요청당 비용.
<dir> 은 samples.jsonl 이 있는 폴더(eval_data/eval_*60, collect_newident.py 출력 모두 됨).
출력: rerank   → <dir>/<model>.jsonl      jev.jsonl 과 같은 줄 형식 {"i","k","probs",...} → eval_rerank.py report (RERANK_FILE)
      generate → <dir>/<model>-gen.jsonl  {"i","k","guesses":[...],...} → gen_report.py
키: 환경 변수 ANTHROPIC_API_KEY (run_claude.sh 가 claude.env 에서 읽음). --dry-run 은 키 없이 토큰·비용만 추정한다.
"""
import argparse, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

SYSTEM = {
    "rerank": ("You rank code-completion candidates for a C/C++ programmer. You see the code before the cursor, ending in "
               "<CURSOR>, and the candidates the language server offers there. Predict which candidate the programmer will "
               "insert at <CURSOR>. Answer with candidate names spelled exactly as listed, most likely first."),
    "generate": ("You predict what a C/C++ programmer types next. You see the code before the cursor, ending in <CURSOR>. "
                 "The next token is one identifier: a variable, function, type, member, namespace or macro name. It may be a "
                 "name that is being declared for the first time. Give up to 5 guesses, most likely first."),
}
SCHEMA = {
    "rerank": {"type": "object", "properties": {"ranking": {"type": "array", "items": {"type": "string"}}},
               "required": ["ranking"], "additionalProperties": False},
    "generate": {"type": "object", "properties": {"guesses": {"type": "array", "items": {"type": "string"}}},
                 "required": ["guesses"], "additionalProperties": False},
}
PRICE = {  # $/M 토큰 (입력, 출력), 2026-10 기준 정가. 배치는 절반.
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
    "jev": (0.042, 0.042),  # 신선셋 실측: 9.0M 토큰 $0.38 → 약 $0.042/M (입출력 구분 없음)
}
OUT_TOK_EST = 150   # 요청당 출력 토큰 추정(짧은 JSON + 낮은 effort 의 적응형 사고)
FALLBACK = [True]   # 서버측 fallback 을 거부하는 모델/경로면 한 번 실패한 뒤 끈다


def trim_state(state, ctx):
    """커서 앞 ctx 줄만 남기고 커서 뒤는 버린다(top-down 조건)."""
    before = state.split("<CURSOR>")[0]
    return "\n".join(before.split("\n")[-ctx:]) + "<CURSOR>"


def build_user(mode, s, k, lv, ctx, topn):
    typed = s["gold"][:int(k)]
    parts = ["```cpp\n" + trim_state(lv["state"], ctx) + "\n```"]
    if typed:
        parts.append(f'The programmer has typed "{typed}" so far: the identifier at <CURSOR> starts with "{typed}".')
    if mode == "rerank":
        parts.append("Candidates (name — detail):")
        parts += [f"{i + 1}. {c['name']} — {c.get('detail', '')}" for i, c in enumerate(lv["cands"])]
        parts.append(f"Return the top {topn} candidate names, most likely first.")
    else:
        parts.append("Return up to 5 identifier guesses, most likely first (just the identifier, no punctuation)."
                     + (f' Every guess must start with "{typed}".' if typed else ""))
    return "\n".join(parts)


def params(mode, args, user):
    return dict(model=args.model, max_tokens=args.max_tokens, system=SYSTEM[mode],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": args.effort, "format": {"type": "json_schema", "schema": SCHEMA[mode]}})


def parse_message(mode, msg, lv):
    """Message 객체 → (기록 공통 필드, 정렬/추측 결과)."""
    rec = {"model": msg.model, "in_tok": msg.usage.input_tokens, "out_tok": msg.usage.output_tokens, "stop": msg.stop_reason}
    if msg.stop_reason == "refusal":
        rec["error"] = "refusal"
        return rec, None
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        rec["error"], rec["raw"] = "json", text[:200]
        return rec, None
    if mode == "rerank":
        names = [c["name"] for c in lv["cands"]]
        seen, ranking = set(), []
        for n in data.get("ranking", []):
            n = str(n).strip()
            if n in names and n not in seen:
                seen.add(n)
                ranking.append(n)
        return rec, {"probs": {n: round(0.5 ** r, 6) for r, n in enumerate(ranking)}}
    return rec, {"guesses": [str(g).strip() for g in data.get("guesses", [])][:5]}


def out_path(mode, args):
    return os.path.join(args.dir, args.model + ("-gen" if mode == "generate" else "") + (f"-{args.tag}" if args.tag else "") + ".jsonl")


def load_jobs(mode, args):
    samples = [json.loads(l) for l in open(os.path.join(args.dir, "samples.jsonl"))]
    if args.limit:
        samples = samples[:args.limit]
    done = set()
    p = out_path(mode, args)
    if os.path.exists(p):
        done = {(r["i"], r["k"]) for r in map(json.loads, open(p))}
    jobs = [(i, k) for i, s in enumerate(samples) for k in s["levels"] if (i, k) not in done]
    return samples, jobs, done


def estimate(mode, args, samples, jobs, client=None):
    chars = [len(SYSTEM[mode]) + len(build_user(mode, samples[i], k, samples[i]["levels"][k], args.ctx, args.topn)) for i, k in jobs]
    tok = [c / 3.6 + 30 for c in chars]   # 대략값: 코드 텍스트 약 3.6자/토큰
    note = "문자 수/3.6 추정"
    if client is not None and jobs:
        probe = jobs[:: max(1, len(jobs) // 20)][:20]
        counted = []
        for i, k in probe:
            p = params(mode, args, build_user(mode, samples[i], k, samples[i]["levels"][k], args.ctx, args.topn))
            counted.append(client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"]).input_tokens)
        ratio = sum(counted) / sum(tok[jobs.index(j)] for j in probe)
        tok = [t * ratio for t in tok]
        note = f"count_tokens {len(probe)}건으로 보정(비율 {ratio:.2f})"
    total_in = sum(tok)
    print(f"{mode}: 요청 {len(jobs)}건, 입력 토큰 약 {total_in / 1e6:.2f}M (요청당 {total_in / max(1, len(jobs)):.0f}; {note}), "
          f"출력 요청당 {OUT_TOK_EST} 가정")
    print(f"{'모델':<18}{'동기 $':>9}{'배치 $':>9}")
    for m, (pi, po) in PRICE.items():
        cost = total_in / 1e6 * pi + len(jobs) * OUT_TOK_EST / 1e6 * po
        print(f"{m:<18}{cost:>9.2f}{cost / 2:>9.2f}")


def call(client, mode, args, user):
    import anthropic
    kw = params(mode, args, user)
    if FALLBACK[0]:
        try:
            return client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except anthropic.BadRequestError as e:
            print("서버측 fallback 없이 진행:", str(e)[:120], flush=True)
            FALLBACK[0] = False
    return client.messages.create(**kw)


def run_sync(mode, args):
    import anthropic
    samples, jobs, done = load_jobs(mode, args)
    if args.dry_run or args.count_tokens:
        client = anthropic.Anthropic() if args.count_tokens else None
        return estimate(mode, args, samples, jobs, client)
    client = anthropic.Anthropic(max_retries=6)
    p = out_path(mode, args)
    print(f"{mode} {args.model}: {len(jobs)}건 호출 (이미 완료 {len(done)}건) → {p}", flush=True)

    def one(i, k):
        lv = samples[i]["levels"][k]
        t0 = time.perf_counter()
        msg = call(client, mode, args, build_user(mode, samples[i], k, lv, args.ctx, args.topn))
        rec, data = parse_message(mode, msg, lv)
        rec.update({"i": i, "k": k, "ms": (time.perf_counter() - t0) * 1000})
        rec.update(data or ({"probs": {}} if mode == "rerank" else {"guesses": []}))
        return rec

    errs = 0
    with open(p, "a") as f, ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(one, i, k) for i, k in jobs]
        for n, fu in enumerate(as_completed(futs), 1):
            try:
                r = fu.result()
                errs += "error" in r
                f.write(json.dumps(r) + "\n")
                f.flush()
            except Exception as e:  # 실패 건은 다음 실행에서 다시 시도된다
                errs += 1
                print("오류:", type(e).__name__, str(e)[:200], flush=True)
            if n % 100 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)
    print(f"끝. 오류/거부 {errs}건. 결과 {p}")


def batch_meta(mode, args):
    return out_path(mode, args) + ".batch.json"


def batch_submit(mode, args):
    import anthropic
    samples, jobs, done = load_jobs(mode, args)
    if args.dry_run:
        return estimate(mode, args, samples, jobs)
    client = anthropic.Anthropic()
    reqs = [{"custom_id": f"{i}-{k}", "params": params(mode, args, build_user(mode, samples[i], k, samples[i]["levels"][k], args.ctx, args.topn))}
            for i, k in jobs]
    b = client.messages.batches.create(requests=reqs)
    meta = {"id": b.id, "mode": mode, "model": args.model, "dir": args.dir, "n": len(reqs), "limit": args.limit, "created": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(meta, open(batch_meta(mode, args), "w"), ensure_ascii=False, indent=1)
    print(f"배치 {b.id} 제출: {len(reqs)}건 ({b.processing_status}). 결과: claude_eval.py batch-fetch {mode} {args.dir} --model {args.model}")


def batch_fetch(mode, args):
    import anthropic
    meta = json.load(open(batch_meta(mode, args)))
    client = anthropic.Anthropic()
    b = client.messages.batches.retrieve(meta["id"])
    rc = b.request_counts
    print(f"배치 {b.id}: {b.processing_status} (처리 중 {rc.processing}, 성공 {rc.succeeded}, 오류 {rc.errored}, 만료 {rc.expired})")
    if b.processing_status != "ended":
        return
    samples, _, done = load_jobs(mode, args)
    p = out_path(mode, args)
    n = errs = 0
    with open(p, "a") as f:
        for res in client.messages.batches.results(b.id):
            i, k = res.custom_id.split("-")
            i = int(i)
            if (i, k) in done:
                continue
            if res.result.type != "succeeded":
                errs += 1
                f.write(json.dumps({"i": i, "k": k, "error": res.result.type, **({"probs": {}} if mode == "rerank" else {"guesses": []})}) + "\n")
                continue
            rec, data = parse_message(mode, res.result.message, samples[i]["levels"][k])
            errs += "error" in rec
            rec.update({"i": i, "k": k, "ms": None, "batch": True})
            rec.update(data or ({"probs": {}} if mode == "rerank" else {"guesses": []}))
            f.write(json.dumps(rec) + "\n")
            n += 1
    print(f"{n}건 기록 (오류/거부 {errs}건) → {p}")


def genmatch(args):
    samples = [json.loads(l) for l in open(os.path.join(args.dir, "samples.jsonl"))]
    src = os.path.join(args.dir, args.model + "-gen" + (f"-{args.tag}" if args.tag else "") + ".jsonl")
    dst = src.replace("-gen", "-genmatch")
    n = hit = 0
    with open(dst, "w") as f:
        for l in open(src):
            r = json.loads(l)
            names = [c["name"] for c in samples[r["i"]]["levels"][str(r["k"])]["cands"]]
            g = [x for x in r.get("guesses") or [] if x in names]
            n += 1; hit += bool(g)
            r.pop("guesses", None)
            r["probs"] = {x: round(0.5 ** j, 6) for j, x in enumerate(g)}
            f.write(json.dumps(r) + "\n")
    print(f"{n}건 → {dst} (추측이 후보와 하나라도 겹침 {100 * hit / max(1, n):.1f}%)")


def price_of(model):
    for m, pr in PRICE.items():
        if model.startswith(m) or m.startswith(model.split("-20")[0]):
            return pr
    return (0.0, 0.0)


def compare(args):
    """clangd 와 재정렬 결과 파일들을 같은 (i,k) 집합에서 비교하고, 토큰·비용·지연까지 한 표에 찍는다."""
    import glob
    samples = [json.loads(l) for l in open(os.path.join(args.dir, "samples.jsonl"))]
    files = args.files.split(",") if args.files else (["jev.jsonl"] if os.path.exists(os.path.join(args.dir, "jev.jsonl")) else []) + \
        sorted(os.path.basename(f) for f in glob.glob(os.path.join(args.dir, "claude-*.jsonl")) if "-gen" not in os.path.basename(f))
    preds = {}
    for f in files:
        d = {}
        for l in open(os.path.join(args.dir, f)):
            r = json.loads(l)
            d[(r["i"], str(r["k"]))] = r
        preds[f.replace(".jsonl", "")] = d
    if not preds:
        sys.exit("비교할 결과 파일이 없다 (jev.jsonl / claude-*.jsonl)")
    keys = [(i, k) for i, s in enumerate(samples) for k in s["levels"]]
    common = [key for key in keys if all(key in d for d in preds.values())
              and samples[key[0]]["gold"] in {c["name"] for c in samples[key[0]]["levels"][key[1]]["cands"]}]  # 정답이 후보에 있는 자리만
    if args.limit:
        common = [key for key in common if key[0] < args.limit]
    ks = sorted({k for _, k in common})
    print(f"{args.dir}: 위치 {len({i for i, _ in common})}곳, 요청 {len(common)}건 (모든 파일에 있는 교집합; 전체 {len(keys)}건)")
    cols = ["clangd"] + list(preds)

    def rank_of(name, names, pred):
        if pred is None:
            return names.index(name) + 1
        order = sorted(names, key=lambda n: (-pred["probs"].get(n, 0.0), names.index(n)))
        return order.index(name) + 1

    st = {c: {k: {"n": 0, "r1": 0, "r5": 0, "rr": 0.0} for k in ks} for c in cols}
    kind_st = {c: {} for c in cols}
    usage = {c: {"in": 0, "out": 0, "ms": [], "err": 0, "batch": 0} for c in preds}
    for i, k in common:
        s = samples[i]
        lv = s["levels"][k]
        names = [c["name"] for c in lv["cands"]]
        kind = s.get("kind") or "ident"
        for c in cols:
            pred = None if c == "clangd" else preds[c][(i, k)]
            r = rank_of(s["gold"], names, pred)
            a = st[c][k]
            a["n"] += 1; a["r1"] += r == 1; a["r5"] += r <= 5; a["rr"] += 1 / r
            if k == "0":
                b = kind_st[c].setdefault(kind, [0, 0]); b[0] += 1; b[1] += r == 1
            if pred is not None:
                u = usage[c]
                u["in"] += pred.get("in_tok") or 0; u["out"] += pred.get("out_tok") or 0
                u["err"] += "error" in pred; u["batch"] += bool(pred.get("batch"))
                if pred.get("ms") is not None:
                    u["ms"].append(pred["ms"])

    def pct(a, n):
        return f"{100 * a / n:5.1f}%" if n else "  -  "
    w = max(12, max(len(c) for c in cols) + 1)
    hdr = "접두어 | " + " | ".join(f"{c:>{w}}" for c in cols)
    for title, f in (("R@1 (미리 선택 항목이 정답)", lambda a: pct(a["r1"], a["n"])),
                     ("MRR", lambda a: f"{a['rr'] / a['n']:.3f}" if a["n"] else "-"),
                     ("R@5", lambda a: pct(a["r5"], a["n"]))):
        print(f"\n{title}\n{hdr}")
        for k in ks:
            print(f"  {k}글자 | " + " | ".join(f"{f(st[c][k]):>{w}}" for c in cols))
        if title.startswith("R@1") and args.ref:
            for ref in args.ref:
                name, vals = ref.split("=")
                print(f"  (참고 {name}: " + " / ".join(f"{k}글자 {v}%" for k, v in zip(ks, vals.split("/"))) + ", 같은 세트의 기존 표에서 옮김)")
    print("\n위치 종류별 R@1, 0글자\n종류   |  n  | " + " | ".join(f"{c:>{w}}" for c in cols))
    for kind in ("member", "scope", "ident"):
        n = kind_st["clangd"].get(kind, [0, 0])[0]
        print(f"{kind:6s} | {n:3d} | " + " | ".join(f"{pct(*reversed(kind_st[c].get(kind, [0, 0]))):>{w}}" for c in cols))

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")
    print(f"\n비용·지연 (정가 기준, 배치 건은 절반 적용)\n{'모델':<{w}} | 오류 | 입력tok/요청 | 출력tok/요청 | 중앙값ms |  p90ms | 실제 $ | $/1000요청 | 전체세트 $")
    for c, u in usage.items():
        n = len(common)
        pi, po = price_of(c)
        cost = (u["in"] * pi + u["out"] * po) / 1e6
        if u["batch"]:
            cost *= 1 - 0.5 * u["batch"] / n
        total_n = len(keys)
        print(f"{c:<{w}} | {u['err']:4d} | {u['in'] / n:12.0f} | {u['out'] / n:12.0f} | {q(u['ms'], .5):8.0f} | {q(u['ms'], .9):6.0f} | {cost:6.3f} | {1000 * cost / n:10.3f} | {cost * total_n / n:9.2f}")
    print("(Jev 단가는 신선셋 실측 평균 $0.042/M 근사. Claude 출력 토큰에는 적응형 사고가 포함된다.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["rerank", "generate", "batch-submit", "batch-fetch", "compare", "genmatch"])
    ap.add_argument("rest", nargs="+", help="<dir> 또는 (batch-*) rerank|generate <dir>")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--max-tokens", type=int, default=8000, help="적응형 사고 토큰까지 포함한 상한")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="앞에서부터 N개 위치만 (시범 실행용)")
    ap.add_argument("--ctx", type=int, default=40, help="커서 앞 문맥 줄 수 (Kev 와 같은 40)")
    ap.add_argument("--topn", type=int, default=10, help="rerank 에서 돌려받을 상위 후보 수")
    ap.add_argument("--tag", default="", help="출력 파일 이름 꼬리표")
    ap.add_argument("--dry-run", action="store_true", help="호출 없이 요청 수·토큰·비용만 추정")
    ap.add_argument("--count-tokens", action="store_true", help="dry-run 을 count_tokens API 로 보정 (키 필요, 무료)")
    ap.add_argument("--files", default="", help="compare: 비교할 결과 파일들(쉼표). 기본 jev.jsonl + claude-*.jsonl")
    ap.add_argument("--ref", action="append", default=[], help='compare: 참고 R@1 줄, 예 "Kev v4=73.7/89.1/93.6"')
    args = ap.parse_args()
    if args.cmd in ("compare", "genmatch"):
        args.dir = args.rest[0]
        (compare if args.cmd == "compare" else genmatch)(args)
    elif args.cmd.startswith("batch-"):
        mode, args.dir = args.rest[0], args.rest[1]
        (batch_submit if args.cmd == "batch-submit" else batch_fetch)(mode, args)
    else:
        args.dir = args.rest[0]
        run_sync(args.cmd, args)


if __name__ == "__main__":
    main()
