#!/usr/bin/env python3
"""후보에 정답이 없는 자리까지 포함해 식별자 위치를 모은다 (식별자 생성 기능 연구용).

eval_rerank.py collect 와 같은 환경 변수(EVAL_ROOT, EVAL_FILES, EVAL_PER_FILE)를 쓰고 항상 top-down(커서 뒤 없음)이다.
collect_auto.py 로 여러 프로젝트를 돌리려면: COLLECT_SCRIPT=collect_newident.py collect_auto.py <out_root> <proj>...
사용: collect_newident.py <out_dir>   →  <out_dir>/samples.jsonl, <out_dir>/summary.txt

줄 형식은 eval 세트와 같고(file, line, col, gold, kind, levels{k: {cands, clangd_ms, state}}) 분류 필드가 붙는다:
  in_cands: {k: bool}   접두어 k글자에서 clangd 상위 MAX_CANDS 안에 정답이 있는가 (eval 세트는 이게 모두 참인 자리만 담았다)
  seen_file: bool       정답 식별자가 같은 파일에서 커서보다 앞에 이미 나왔는가
  seen_proj: bool       프로젝트의 다른 파일에 나오는가
  prev: str             커서 앞 마지막 토큰 (int, auto, ::, ., -> ...)   next: str  원문에서 식별자 바로 뒤 2자 (=, ;, (, ::, ...)
  cls: "cand" (0글자 후보에 있음 = 기존 평가 자리) / "decl" (앞이 타입, 뒤가 = ; , ) ( { 인 선언 자리 = 생성 대상)
       / "miss" (전에 나온 이름인데 후보에 없음: 헤더 못 찾음·매크로·파싱 실패·후보 한도) / "new" (그 외 처음 보는 이름)
clangd 가 파싱에 실패한 파일은 miss 가 많이 나오므로(후보 0개 또는 키워드만) 프로젝트별 summary 로 걸러 본다.
"""
import json, os, random, re, sys, time

os.environ.setdefault("EVAL_TOPDOWN", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_rerank as er  # noqa: E402  (ROOT, FILES, PER_FILE, PREFIXES, CTX_BEFORE, Clangd, code_identifiers, candidates)

SRC_EXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".inl", ".ipp")
TOK = re.compile(r"[A-Za-z_]\w*|::|->|\S")


def project_idents(root):
    """파일별 식별자 집합 (프로젝트 안 다른 파일 등장 여부용). .git, build 는 뺀다."""
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in (".git", "build") and not d.startswith(".")]
        for fn in fns:
            if fn.endswith(SRC_EXT):
                p = os.path.join(dp, fn)
                try:
                    out[os.path.relpath(p, root)] = {w for _, _, w in er.code_identifiers(open(p, errors="replace").read())}
                except OSError:
                    pass
    return out


NOT_TYPE = {"return", "case", "goto", "new", "delete", "throw", "sizeof", "typeid", "co_return", "co_yield", "co_await",
            "else", "do", "if", "while", "for", "switch", "using", "operator", "this", "nullptr", "true", "false", "break",
            "continue", "default", "public", "private", "protected", "virtual", "override", "final", "noexcept"}
TYPE_WORDS = {"auto", "const", "constexpr", "static", "inline", "volatile", "mutable", "unsigned", "signed", "long", "short",
              "int", "char", "bool", "float", "double", "void", "struct", "class", "enum", "union", "namespace", "typename",
              "template", "friend", "extern", "register", "thread_local", "decltype"}


def is_decl(prev, nxt):
    """선언 자리 추정: 앞 토큰이 타입처럼 보이고(식별자·키워드·> * &) 뒤가 = ; , ) ( { [ : 이면 새 이름을 짓는 자리."""
    if not prev or prev in NOT_TYPE:
        return False
    typeish = prev in TYPE_WORDS or prev in (">", "*", "&", "&&") or (prev[0].isalpha() or prev[0] == "_") and prev not in er.KEYWORDS
    return typeish and bool(nxt) and nxt[0] in "=;,)({[:"


def classify(rec):
    """cand: 0글자 후보에 있음 / decl: 선언 자리(생성 대상) / miss: 전에 나온 이름인데 후보에 없음(파싱 실패·한도) / new: 그 외 처음 보는 이름."""
    if rec["in_cands"].get("0"):
        return "cand"
    if is_decl(rec["prev"], rec["next"]):
        return "decl"
    return "miss" if (rec["seen_file"] or rec["seen_proj"]) else "new"


def main():
    out_dir = sys.argv[1]
    os.makedirs(out_dir, exist_ok=True)
    rng = random.Random(42)
    proj = project_idents(er.ROOT)
    cd = er.Clangd()
    out = open(os.path.join(out_dir, "samples.jsonl"), "w")
    stat = {}

    def bump(*key):
        stat[key] = stat.get(key, 0) + 1

    for rel in er.FILES:
        path = os.path.join(er.ROOT, rel)
        uri = "file://" + path
        src = open(path, errors="replace").read()
        lines = src.split("\n")
        idents = er.code_identifiers(src)
        picks = sorted(rng.sample(idents, min(er.PER_FILE, len(idents))))
        others = set().union(*(s for f, s in proj.items() if f != rel)) if len(proj) > 1 else set()
        lang = "c" if rel.endswith(".c") else "cpp"
        cd.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": lang, "version": 1, "text": src}})
        while cd.recv().get("method") != "textDocument/publishDiagnostics":
            pass
        ver = kept = 0
        for ln, col, w in picks:
            lead = lines[ln][:col].rstrip()
            kind = "member" if lead.endswith((".", "->")) else "scope" if lead.endswith("::") else "ident"
            head = "\n".join(lines[:ln]) + "\n" + lines[ln][:col]
            seen_file = bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", head))
            prev_toks = TOK.findall(" ".join(lines[max(0, ln - 1):ln]) + " " + lines[ln][:col])
            after = lines[ln][col + len(w):].lstrip()
            rec = {"file": rel, "line": ln, "col": col, "gold": w, "kind": kind, "levels": {}, "in_cands": {},
                   "seen_file": seen_file, "seen_proj": w in others, "prev": prev_toks[-1] if prev_toks else "", "next": after[:2]}
            for k in er.PREFIXES:
                if k >= len(w):
                    break
                cur = lines[ln][:col] + w[:k]
                text = "\n".join(lines[:ln] + [cur])
                ver += 1
                cd.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": ver}, "contentChanges": [{"text": text}]})
                t0 = time.perf_counter()
                res = cd.req("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": ln, "character": col + k}})
                ms = (time.perf_counter() - t0) * 1000
                cands = er.candidates(res)
                state = "\n".join(lines[max(0, ln - er.CTX_BEFORE):ln] + [cur + "<CURSOR>"])
                rec["levels"][str(k)] = {"cands": cands, "clangd_ms": ms, "state": state}
                rec["in_cands"][str(k)] = w in [c["name"] for c in cands]
            if not rec["levels"]:
                continue
            rec["cls"] = classify(rec)
            out.write(json.dumps(rec) + "\n")
            kept += 1
            bump("cls", rec["cls"])
            bump("cls_kind", rec["cls"], kind)
            bump("cls_next", rec["cls"], rec["next"][:1] or "EOL")
            for k, v in rec["in_cands"].items():
                bump("in_cands", k, v)
        cd.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        print(f"{rel}: {kept}곳", flush=True)
    cd.close()
    out.close()

    n = sum(v for k, v in stat.items() if k[0] == "cls")
    rows = [f"위치 {n}곳 (프로젝트 {er.ROOT})", "분류(0글자 기준): " + ", ".join(
        f"{c} {stat.get(('cls', c), 0)} ({100 * stat.get(('cls', c), 0) / max(1, n):.1f}%)" for c in ("cand", "decl", "miss", "new"))]
    for k in map(str, er.PREFIXES):
        t = stat.get(("in_cands", k, True), 0); f = stat.get(("in_cands", k, False), 0)
        rows.append(f"{k}글자: 후보에 정답 있음 {t}, 없음 {f} ({100 * f / max(1, t + f):.1f}%)")
    for c in ("decl", "miss", "new"):
        rows.append(f"{c} 종류별: " + ", ".join(f"{kd} {stat.get(('cls_kind', c, kd), 0)}" for kd in ("ident", "member", "scope")))
        nxt = sorted(((v, k[2]) for k, v in stat.items() if k[:2] == ("cls_next", c)), reverse=True)[:8]
        rows.append(f"{c} 뒤 문자: " + ", ".join(f"'{ch}' {v}" for v, ch in nxt))
    open(os.path.join(out_dir, "summary.txt"), "w").write("\n".join(rows) + "\n")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
