"""clangd 단독 / clangd+VS Code 기억 / Jev / Jev+기억 비교 평가.

1단계(collect): 소스의 식별자 위치를 뽑아, 식별자를 접두어 k글자(0,1,2)만 남기고 지운 뒤
              clangd 완성 후보를 받는다. 결과는 samples.jsonl에 저장.
2단계(jev):    각 (위치, k)마다 Jev Choice로 후보를 재정렬. jev.jsonl에 저장(재실행 시 이어서).
3단계(report): 파일 순서대로 VS Code recentlyUsedByPrefix를 흉내 내며 지표 계산.

사용: eval_rerank.py collect|jev|report <out_dir>

환경 변수(collect):
  EVAL_ROOT     프로젝트 루트 (기본: ext/fmt)
  EVAL_FILES    쉼표로 구분한 상대 경로 (기본: fmt 파일 목록)
  EVAL_TOPDOWN  1이면 커서 뒤 내용을 clangd와 모델 양쪽에서 지운다 ("위에서부터 새로 쓰는" 상황)
  EVAL_PER_FILE 파일당 유효 샘플 상한 (기본 50)
"""
import json, os, random, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.environ.get("EVAL_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ext", "fmt")
FILES = (os.environ["EVAL_FILES"].split(",") if os.environ.get("EVAL_FILES") else
         ["src/os.cc", "test/core-test.cc", "test/format-test.cc", "test/ranges-test.cc",
          "test/chrono-test.cc", "test/printf-test.cc", "test/std-test.cc", "test/os-test.cc",
          "test/compile-test.cc", "test/xchar-test.cc", "test/args-test.cc"])
TOPDOWN = os.environ.get("EVAL_TOPDOWN") == "1"
PREFIXES = [0, 1, 2]
PER_FILE = int(os.environ.get("EVAL_PER_FILE", "50"))  # 파일당 유효 샘플 상한
OVERSAMPLE = PER_FILE * 3   # 파일당 후보 위치 수 (정답이 후보에 없는 위치는 버린다)
MAX_CANDS = 255        # Jev Choice 상한
CTX_BEFORE, CTX_AFTER = 80, (0 if TOPDOWN else 10)

KEYWORDS = set("""alignas alignof and asm auto bitand bitor bool break case catch char char8_t char16_t
char32_t class compl concept const consteval constexpr constinit const_cast continue co_await co_return
co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for
friend goto if inline int long mutable namespace new noexcept not nullptr operator or private protected
public register reinterpret_cast requires return short signed sizeof static static_assert static_cast
struct switch template this thread_local throw true try typedef typeid typename union unsigned using
virtual void volatile wchar_t while override final""".split())


def code_identifiers(src):
    """주석, 문자열, 전처리 줄을 건너뛰고 (line, col, ident) 목록을 돌려준다."""
    out = []
    lines = src.split("\n")
    in_block = False
    for ln, line in enumerate(lines):
        if not in_block and line.lstrip().startswith("#"):
            continue
        i = 0
        while i < len(line):
            if in_block:
                j = line.find("*/", i)
                if j < 0:
                    break
                in_block, i = False, j + 2
                continue
            ch = line[i]
            if line.startswith("//", i):
                break
            if line.startswith("/*", i):
                in_block, i = True, i + 2
                continue
            if ch in "\"'":
                # R"(...)" 같은 raw string은 단순 처리: 같은 줄의 닫는 따옴표까지 건너뛴다
                j = i + 1
                while j < len(line) and line[j] != ch:
                    j += 2 if line[j] == "\\" else 1
                i = j + 1
                continue
            m = re.match(r"[A-Za-z_]\w*", line[i:])
            if m:
                w = m.group(0)
                prev = line[:i].rstrip()
                if len(w) >= 3 and w not in KEYWORDS and not prev.endswith(("#", "'")):
                    out.append((ln, i, w))
                i += len(w)
                continue
            i += 1
    return out


class Clangd:
    def __init__(self):
        self.p = subprocess.Popen(["/usr/bin/clangd", "--log=error", "--limit-results=300"],
                                  cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
        self.n = 0
        self.req("initialize", {"processId": None, "rootUri": "file://" + ROOT, "capabilities": {}})
        self.notify("initialized", {})

    def send(self, m):
        b = json.dumps(m).encode()
        self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b)
        self.p.stdin.flush()

    def recv(self):
        h = {}
        while True:
            l = self.p.stdout.readline().decode().strip()
            if not l:
                break
            k, v = l.split(":", 1)
            h[k] = v
        return json.loads(self.p.stdout.read(int(h["Content-Length"])))

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def req(self, method, params):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            m = self.recv()
            if m.get("id") == self.n:
                return m.get("result")

    def close(self):
        self.p.kill()


# LSP CompletionItemKind -> 이름. clangd는 네임스페이스를 Module(9)로 보낸다.
KIND_NAMES = {1: "text", 2: "method", 3: "function", 4: "constructor", 5: "field", 6: "variable", 7: "class",
              8: "interface", 9: "namespace", 10: "property", 12: "value", 13: "enum", 14: "keyword",
              15: "snippet", 17: "file", 20: "enum member", 21: "constant", 22: "struct", 25: "type parameter"}


def candidates(result):
    items = result["items"] if isinstance(result, dict) else (result or [])
    by_name = {}
    for it in sorted(items, key=lambda x: x["sortText"]):
        name = it.get("filterText") or it["label"].strip()
        if name not in by_name:
            # 설명은 v1 형식을 유지한다 (종류를 설명에 넣으면 Jev 정확도가 떨어졌다). 종류는 따로 보관.
            kind = KIND_NAMES.get(it.get("kind"), "symbol")
            detail = (it["label"].strip() + " -> " + it.get("detail", "")).strip()
            by_name[name] = {"name": name, "kind": kind, "detail": detail}
    return list(by_name.values())[:MAX_CANDS]


def collect(out_dir):
    rng = random.Random(42)
    cd = Clangd()
    out = open(os.path.join(out_dir, "samples.jsonl"), "w")
    total_tried = total_kept = 0
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        uri = "file://" + path
        src = open(path).read()
        lines = src.split("\n")
        idents = code_identifiers(src)
        picks = sorted(rng.sample(idents, min(OVERSAMPLE, len(idents))))
        lang = "c" if rel.endswith(".c") else "cpp"
        cd.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": lang, "version": 1, "text": src}})
        while cd.recv().get("method") != "textDocument/publishDiagnostics":
            pass
        ver, kept = 1, 0
        for ln, col, w in picks:
            if kept >= PER_FILE:
                break
            total_tried += 1
            lead = lines[ln][:col].rstrip()
            kind = ("member" if lead.endswith((".", "->")) else "scope" if lead.endswith("::") else "ident")
            rec = {"file": rel, "line": ln, "col": col, "gold": w, "kind": kind, "levels": {}}
            ok = True
            for k in PREFIXES:
                if k >= len(w):
                    ok = False
                    break
                cur = lines[ln][:col] + w[:k]
                text = "\n".join(lines[:ln] + [cur] + ([] if TOPDOWN else lines[ln + 1:]))
                ver += 1
                cd.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": ver},
                                                     "contentChanges": [{"text": text}]})
                t0 = time.perf_counter()
                res = cd.req("textDocument/completion", {"textDocument": {"uri": uri},
                                                         "position": {"line": ln, "character": col + k}})
                ms = (time.perf_counter() - t0) * 1000
                cands = candidates(res)
                names = [c["name"] for c in cands]
                if w not in names:
                    ok = False
                    break
                before = lines[max(0, ln - CTX_BEFORE):ln]
                after = lines[ln + 1:ln + 1 + CTX_AFTER]
                state = "\n".join(before + [cur + "<CURSOR>"] + after)
                rec["levels"][str(k)] = {"cands": cands, "clangd_ms": ms, "state": state}
            if ok:
                out.write(json.dumps(rec) + "\n")
                kept += 1
                total_kept += 1
        cd.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        print(f"{rel}: 유효 {kept}개", flush=True)
    cd.close()
    print(f"시도 {total_tried}, 유효 {total_kept} (정답이 후보에 없거나 너무 짧아 제외 {total_tried - total_kept})")


def jev(out_dir):
    from typesafe_sdk import Choice, TypeSafeClient
    # RERANK_BASE_URL을 주면 같은 API의 로컬 서버(Kev)로 보낸다. Kev는 키를 요구하지 않는다.
    base_url = os.environ.get("RERANK_BASE_URL")
    client = (TypeSafeClient(base_url=base_url, api_key="local", model=os.environ.get("RERANK_MODEL", "kev-latest"))
              if base_url else TypeSafeClient())
    samples = [json.loads(l) for l in open(os.path.join(out_dir, "samples.jsonl"))]
    done_path = os.path.join(out_dir, "jev.jsonl")
    done = set()
    if os.path.exists(done_path):
        for l in open(done_path):
            r = json.loads(l)
            done.add((r["i"], r["k"]))
    jobs = [(i, k) for i, s in enumerate(samples) for k in s["levels"] if (i, k) not in done]
    print(f"Jev 호출 {len(jobs)}건 (이미 완료 {len(done)}건)", flush=True)

    def call(i, k):
        lv = samples[i]["levels"][k]
        t0 = time.perf_counter()
        typed = samples[i]["gold"][:int(k)]
        if os.environ.get("RERANK_PROMPT") == "v2":
            # 친 글자를 명시하고, 최종 목표 함수가 아니라 지금 커서에서 끝날 토큰 하나를 고르게 한다
            instructions = ("C/C++ code with a <CURSOR> marker. "
                            + (f"The programmer has typed \"{typed}\" just before <CURSOR>. " if typed else "")
                            + "Which single identifier token completes the word at <CURSOR>? "
                              "Pick the token itself, not a symbol that would come after a following '::' or '.'.")
        else:
            instructions = "C++ code with a <CURSOR> marker. Which identifier will the programmer most likely type at <CURSOR>?"
        resp = client.system_one(
            state=lv["state"],
            questions={"next": Choice(
                instructions=instructions,
                criteria={c["name"]: c["detail"] for c in lv["cands"]})})
        ms = (time.perf_counter() - t0) * 1000
        a = resp.answers["next"]
        return {"i": i, "k": k, "probs": a.probabilities, "ms": ms, "model": resp.model,
                "in_tok": resp.usage.input_tokens}

    with open(done_path, "a") as f, ThreadPoolExecutor(int(os.environ.get("RERANK_WORKERS", "16"))) as ex:
        futs = [ex.submit(call, i, k) for i, k in jobs]
        for n, fu in enumerate(as_completed(futs), 1):
            try:
                f.write(json.dumps(fu.result()) + "\n")
                f.flush()
            except Exception as e:  # 실패 건은 다음 실행에서 다시 시도된다
                print("오류:", type(e).__name__, str(e)[:200], flush=True)
            if n % 100 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)


def report(out_dir):
    samples = [json.loads(l) for l in open(os.path.join(out_dir, "samples.jsonl"))]
    jv = {}
    for l in open(os.path.join(out_dir, "jev.jsonl")):
        r = json.loads(l)
        jv[(r["i"], r["k"])] = r
    memory = {}  # VS Code PrefixMemory: 접두어 -> 고른 이름

    def mem_pick(prefix, names, default):
        if not prefix:  # 빈 접두어면 VS Code는 기억을 쓰지 않는다
            return default
        key = next((prefix[:n] for n in range(len(prefix), 0, -1) if prefix[:n] in memory), None)
        if key and memory[key] in names:
            return memory[key]
        return default

    stats = {k: {"n": 0, "clangd": 0, "clangd_mem": 0, "jev": 0, "jev_mem": 0,
                 "rr_clangd": 0.0, "rr_jev": 0.0, "r5_clangd": 0, "r5_jev": 0} for k in map(str, PREFIXES)}
    jev_ms, clangd_ms, in_tok, models = [], [], [], set()
    by_kind = {}  # (위치 종류, 접두어) -> [n, clangd 정답, 재정렬 정답]
    for i, s in enumerate(samples):
        gold = s["gold"]
        if any((i, k) not in jv for k in s["levels"]):
            continue
        kind = s.get("kind")
        if kind is None:  # 예전 샘플: 커서 앞 텍스트로 판별
            lead = s["levels"]["0"]["state"].split("<CURSOR>")[0].split("\n")[-1].rstrip()
            kind = "member" if lead.endswith((".", "->")) else "scope" if lead.endswith("::") else "ident"
        for k, lv in s["levels"].items():
            names = [c["name"] for c in lv["cands"]]
            j = jv[(i, k)]
            jrank = sorted(names, key=lambda n: (-j["probs"].get(n, 0.0), names.index(n)))
            prefix = gold[:int(k)]
            st = stats[k]
            st["n"] += 1
            st["clangd"] += names[0] == gold
            st["clangd_mem"] += mem_pick(prefix, names, names[0]) == gold
            st["jev"] += jrank[0] == gold
            st["jev_mem"] += mem_pick(prefix, names, jrank[0]) == gold
            rc, rj = names.index(gold) + 1, jrank.index(gold) + 1
            st["rr_clangd"] += 1 / rc
            st["rr_jev"] += 1 / rj
            st["r5_clangd"] += rc <= 5
            st["r5_jev"] += rj <= 5
            bk = by_kind.setdefault((kind, k), [0, 0, 0])
            bk[0] += 1
            bk[1] += rc == 1
            bk[2] += rj == 1
            jev_ms.append(j["ms"])
            clangd_ms.append(lv["clangd_ms"])
            in_tok.append(j["in_tok"])
            models.add(j["model"])
        # 사용자가 1글자, 2글자 뒤에 정답을 골랐다고 가정하고 기억에 쌓는다 (기억 기능에 유리한 가정)
        for k in PREFIXES[1:]:
            memory[gold[:k]] = gold

    def pct(a, n):
        return f"{100 * a / n:5.1f}%" if n else "  -  "

    print(f"Jev 모델: {', '.join(sorted(models))}")
    print(f"샘플 위치 {stats['0']['n']}곳, 접두어 0/1/2글자\n")
    print("미리 선택된 항목이 정답인 비율 (R@1)")
    print("접두어 | clangd | clangd+기억 |   Jev  | Jev+기억 | n")
    for k, st in stats.items():
        n = st["n"]
        print(f"  {k}글자 | {pct(st['clangd'], n)} |   {pct(st['clangd_mem'], n)}    | {pct(st['jev'], n)} |  {pct(st['jev_mem'], n)}  | {n}")
    print("\n순서 전체 품질 (기억 기능은 순서를 바꾸지 않으므로 clangd vs Jev만)")
    print("접두어 | MRR clangd | MRR Jev | R@5 clangd | R@5 Jev")
    for k, st in stats.items():
        n = st["n"]
        print(f"  {k}글자 |   {st['rr_clangd'] / n:.3f}    |  {st['rr_jev'] / n:.3f}  |   {pct(st['r5_clangd'], n)}   | {pct(st['r5_jev'], n)}")

    print("\n위치 종류별 R@1 (clangd -> 재정렬)")
    print("종류   |  n  |  0글자          |  1글자          |  2글자")
    for kind in ("member", "scope", "ident"):
        cells = []
        for k in map(str, PREFIXES):
            n, c, r = by_kind.get((kind, k), [0, 0, 0])
            cells.append(f"{pct(c, n)} -> {pct(r, n)}")
        print(f"{kind:6s} | {by_kind.get((kind, '0'), [0])[0]:3d} | " + " | ".join(cells))

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * len(xs)))]
    print(f"\n지연: clangd 중앙값 {q(clangd_ms, .5):.0f}ms, Jev 왕복 중앙값 {q(jev_ms, .5):.0f}ms / p90 {q(jev_ms, .9):.0f}ms")
    print(f"Jev 입력 토큰 합계 {sum(in_tok):,} (요청당 평균 {sum(in_tok) / len(in_tok):.0f})")


if __name__ == "__main__":
    step, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    {"collect": collect, "jev": jev, "report": report}[step](out_dir)
