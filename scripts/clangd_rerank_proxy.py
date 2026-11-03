#!/usr/bin/env python3
"""clangd 앞에 끼우는 LSP 프록시. textDocument/completion 응답만 가로채 재정렬 모델로 순서를 다시 매긴다.

VS Code 설정: "clangd.path": "<이 파일>", "clangd.arguments": [...] (인자는 그대로 clangd에 전달)
환경 변수:
  RERANK_BASE_URL   System One 호환 서버 (기본 http://127.0.0.1:8009 = 로컬 Kev; Jev면 비우고 TYPESAFE_API_KEY 설정)
  RERANK_MODEL      기본 kev-latest (Jev면 jev-latest)
  RERANK_TIMEOUT    초. 넘기면 clangd 순서 그대로 돌려준다 (기본 0.4)
  RERANK_MAX_CANDS  모델에 보내는 후보 수 (기본 60; 나머지는 뒤에 그대로 붙는다)
  RERANK_CTX_LINES  커서 앞 문맥 줄 수 (기본 40)
  RERANK_LOG        로그 파일 경로 (선택)
  RERANK_STATS      실사용 측정 파일(JSONL, 선택). 자동완성 자리마다 사용자가 결국 쓴 식별자와 그 항목의 순위를
                    clangd / 2단계 / 최종 순서별로 적는다 (친 글자 0·1·2개 단계별 한 줄). 코드 본문은 적지 않는다.
                    집계는 rerank_stats.py <파일>.
  CLANGD_BIN        clangd 실행 파일 (기본 clangd)
  STAGE2_MODEL      2단계 LightGBM 모델 파일(stage1_ranker.py 출력). 주면 clangd 후보 전체를 2단계로 먼저 매겨
                    상위 RERANK_MAX_CANDS개만 3단계(모델)에 보낸다. 같은 폴더의 stage2_lite.py(표준 라이브러리만)로 평가한다.
  RERANK_STAGE3     0이면 3단계(모델 호출)를 끄고 2단계 순서만 쓴다 (기본 1)
  RERANK_SKIP3_TYPED 친 글자 수가 이 값 이상이면 3단계를 건너뛰고 2단계 순서만 쓴다 (기본 0 = 항상 3단계; 2차 모델은 2글자에서도 2단계보다 8~9%p 높았다)

동작: 에디터 -> 프록시 -> clangd 는 그대로 전달. clangd -> 에디터 중 completion 응답은
  1) 열린 문서 내용(didOpen/didChange로 추적)에서 커서 앞 문맥을 만들고
  2) 후보 상위 N개를 Choice 질문으로 모델에 보내 확률을 받아
  3) 확률 내림차순으로 sortText 를 다시 써서 돌려준다. 실패·시간 초과면 원본 그대로.
표준 라이브러리만 쓴다 (설치 없이 동작; 2단계도 stage2_lite.py 로 순수 파이썬).
"""
import json, os, re, subprocess, sys, threading, time, urllib.request

BASE_URL = os.environ.get("RERANK_BASE_URL", "http://127.0.0.1:8009").rstrip("/") or "https://api.typesafe.ai"
MODEL = os.environ.get("RERANK_MODEL", "kev-latest")
API_KEY = os.environ.get("TYPESAFE_API_KEY", "local")
TIMEOUT = float(os.environ.get("RERANK_TIMEOUT", "0.4"))
MAX_CANDS = int(os.environ.get("RERANK_MAX_CANDS", "60"))
CTX_LINES = int(os.environ.get("RERANK_CTX_LINES", "40"))
LOG = os.environ.get("RERANK_LOG")
STATS = os.environ.get("RERANK_STATS")
SKIP3_TYPED = int(os.environ.get("RERANK_SKIP3_TYPED", "0"))
INSTRUCTIONS = "C++ code with a <CURSOR> marker. Which identifier will the programmer most likely type at <CURSOR>?"

GEN_URL = os.environ.get("RERANK_GEN_URL", "").rstrip("/")   # 비면 생성 끔
GEN_TIMEOUT = float(os.environ.get("RERANK_GEN_TIMEOUT", "0.8"))
GEN_N = int(os.environ.get("RERANK_GEN_N", "3"))

STAGE3 = os.environ.get("RERANK_STAGE3", "1") != "0"
stage2 = None
if os.environ.get("STAGE2_MODEL"):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import stage2_lite
    stage2 = stage2_lite.LGBModel(os.environ["STAGE2_MODEL"])


def typed_prefix(state):
    """커서 앞에서 사용자가 치고 있는 식별자 조각"""
    m = re.search(r"[A-Za-z_]\w*$", state.rsplit("<CURSOR>", 1)[0].split("\n")[-1])
    return m.group(0) if m else ""


_NOT_TYPE = {"return", "new", "delete", "throw", "case", "goto", "else", "do", "sizeof", "using", "namespace", "operator",
             "template", "if", "while", "for", "switch", "co_return", "co_await", "co_yield", "and", "or", "not",
             "const", "static", "volatile", "constexpr", "unsigned", "signed", "typename", "inline", "extern", "mutable",
             "thread_local", "virtual", "explicit", "friend", "public", "private", "protected", "break", "continue"}
_TYPE_END = re.compile(r"(?:^|[\s(,;{<])([A-Za-z_][\w:]*)(?:\s*<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*(?:[*&]+\s*|\.\.\.\s*)?\s$")


def decl_site(state):
    """커서가 '새 이름을 선언하는 자리'인가: 친 글자 앞이 `Type `, `Type* `, `std::vector<T>& `, `auto ` 꼴이면 참.
    `return x`, `a = b`, `f(x`, `obj.` 처럼 식 자리는 거짓. (정규식 휴리스틱; 프로토타입)"""
    line = state.rsplit("<CURSOR>", 1)[0].split("\n")[-1]
    head = re.sub(r"[A-Za-z_]\w*$", "", line)
    if not head or head.lstrip().startswith("#"):
        return False
    if head[-1] in "*&":  # `Type *name`, `auto &x` (별표가 이름 쪽에 붙은 꼴); `(&x`, `= &x`, `, &x` 는 아니다
        head = head.rstrip("*&")
        if not head or not head[-1].isspace():
            return False
        head = head + " "
    if not head[-1].isspace():
        return False
    m = _TYPE_END.search(head)
    if not m:
        return False
    if re.search(r"\s[*&]\s*$", head) and re.search(r"&&|\|\||\b(if|while|return)\s*\(", line):
        return False  # `(a & ` 같은 이항 연산자
    name = m.group(1).split("::")[-1]
    return name not in _NOT_TYPE


def generate_names(state, typed, existing):
    """선언 자리에서 생성 서버에 새 이름을 묻는다. 이미 보이는 심볼과 겹치는 이름은 뺀다(가짜 심볼 방지)."""
    before = state.rsplit("<CURSOR>", 1)[0]
    if typed:
        before = before[:-len(typed)]
    body = json.dumps({"prefix": before, "typed": typed, "n": GEN_N + 2}).encode()
    req = urllib.request.Request(GEN_URL + "/v1/gen", data=body, method="POST", headers={"content-type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=GEN_TIMEOUT) as r:
        guesses = json.load(r)["guesses"]
    ms = (time.perf_counter() - t0) * 1000
    names = [g for g in guesses if g not in existing][:GEN_N]
    log(f"gen {ms:.0f}ms typed={typed!r} -> {names}")
    return names


def gen_items(names):
    return [{"label": n, "kind": 6, "detail": "✦ 이름 제안 (생성)", "insertText": n, "filterText": n,
             "sortText": f"!{i:03d}", "preselect": i == 0} for i, n in enumerate(names)]


def stage2_order(items, state):
    """2단계: clangd 후보 전체(이름 단위)를 LightGBM 점수 순으로. (이름 목록, 이름->항목들)"""
    name_of = {}
    for it in sorted(items, key=lambda it: it.get("sortText", it["label"])):
        name = it.get("filterText") or it["label"].strip()
        name_of.setdefault(name, []).append(it)
    names = list(name_of)
    if stage2 is None or len(names) < 2:
        return names, name_of
    cands = [{"name": n, "kind": "symbol", "detail": (name_of[n][0]["label"].strip() + " -> " + name_of[n][0].get("detail", "")).strip()}
             for n in names]
    order = stage2_lite.order(stage2, cands, state, len(typed_prefix(state)))
    return [names[i] for i in order], name_of

docs = {}            # uri -> 문서 전체 텍스트
pending = {}         # 에디터가 보낸 completion 요청 id -> (uri, line, character)
lock = threading.Lock()
sites = {}           # 실사용 측정: (uri, line, 단어 시작 col) -> {"levels": {친 글자 수: {순서 이름: [이름...]}}, "t", "away"}
sites_lock = threading.Lock()
IDENT = re.compile(r"[A-Za-z_]\w*")


def log(msg):
    if LOG:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def read_msg(stream):
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.decode().strip()
        if not line:
            break
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return json.loads(stream.read(int(headers["content-length"])))


def write_msg(stream, msg):
    b = json.dumps(msg).encode()
    with lock:
        stream.write(b"Content-Length: %d\r\n\r\n" % len(b) + b)
        stream.flush()


def apply_change(uri, changes):
    """didChange 반영. 전체 교체와 범위 교체 둘 다 처리한다."""
    text = docs.get(uri, "")
    for ch in changes:
        if "range" not in ch:
            text = ch["text"]
            continue
        lines = text.split("\n")
        s, e = ch["range"]["start"], ch["range"]["end"]
        before = "\n".join(lines[:s["line"]] + [lines[s["line"]][:s["character"]]]) if lines else ""
        after = lines[e["line"]][e["character"]:] + ("\n" + "\n".join(lines[e["line"] + 1:]) if e["line"] + 1 < len(lines) else "")
        text = before + ch["text"] + after
    docs[uri] = text


def state_for(uri, line, character):
    lines = docs.get(uri, "").split("\n")
    cur = lines[line][:character] if line < len(lines) else ""
    return "\n".join(lines[max(0, line - CTX_LINES + 1):line] + [cur + "<CURSOR>"])


def emit(order, name_of):
    """이름 순서대로 sortText 를 다시 써서 항목 목록을 만든다 (오버로드는 이름 뒤에 붙어 간다)."""
    out, rank = [], 0
    for name in order:
        for it in name_of[name]:
            it["sortText"] = f"{rank:05d}"
            out.append(it)
            rank += 1
    return out


def rerank(items, state):
    """items: clangd 후보. 2단계(있으면)로 상위 MAX_CANDS개를 고르고, 3단계 모델 확률로 그 안을 재정렬한다."""
    t0 = time.perf_counter()
    names, name_of = stage2_order(items, state)
    ms2 = (time.perf_counter() - t0) * 1000
    head, tail = names[:MAX_CANDS], names[MAX_CANDS:]
    typed = typed_prefix(state)
    info = {"typed": typed, "orders": {"clangd": list(name_of), "stage2": names}}
    if len(head) < 2:
        return None, info
    if stage2 is not None and (not STAGE3 or (SKIP3_TYPED and len(typed) >= SKIP3_TYPED)):
        log(f"stage2 only ({ms2:.1f}ms, typed={typed!r}) top={head[:3]}")
        info["orders"]["final"] = head + tail
        return emit(head + tail, name_of), info
    if not STAGE3:
        return None, info
    criteria = {n: (name_of[n][0]["label"].strip() + " -> " + name_of[n][0].get("detail", "")).strip() for n in head}
    body = json.dumps({"model": MODEL, "state": state,
                       "questions": {"next": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}}}).encode()
    req = urllib.request.Request(BASE_URL + "/v1/systemone", data=body, method="POST",
                                 headers={"content-type": "application/json", "authorization": f"Bearer {API_KEY}"})
    t1 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            probs = json.load(r)["answers"]["next"]["probabilities"]
    except Exception as e:  # 3단계 실패·시간 초과: 2단계 순서라도 돌려준다
        log(f"stage3 skipped: {type(e).__name__} {e}; stage2 order used")
        if stage2 is None:
            return None, info
        info["orders"]["final"] = head + tail
        return emit(head + tail, name_of), info
    ms3 = (time.perf_counter() - t1) * 1000
    order = sorted(head, key=lambda n: -probs.get(n, 0.0))
    log(f"stage2 {ms2:.1f}ms + stage3 {len(head)} cands {ms3:.0f}ms top={order[:3]}")
    info["orders"]["final"] = order + tail
    return emit(order + tail, name_of), info


# ---- 실사용 측정 (RERANK_STATS) ----
def site_open(uri, line, ch, info):
    """completion 응답을 돌려준 자리를 기억한다. 같은 단어 자리(친 글자 수가 다른 요청)는 한 묶음."""
    if not STATS or info is None:
        return
    key = (uri, line, ch - len(info["typed"]))
    with sites_lock:
        s = sites.setdefault(key, {"levels": {}, "t": time.time(), "away": False})
        s["levels"][len(info["typed"])] = info["orders"]
        if len(sites) > 50:  # 오래된 것부터 정리
            for k in sorted(sites, key=lambda k: sites[k]["t"])[:-50]:
                site_close(k, docs.get(k[0], ""), force=True)


def word_at(text, line, col):
    lines = text.split("\n")
    ltxt = lines[line] if line < len(lines) else ""
    m = IDENT.match(ltxt[col:])
    return (m.group(0) if m else ""), ltxt


def site_close(key, text, force=False):
    """자리의 단어가 끝났으면(뒤에 다른 글자가 있거나 다른 곳을 편집) 순위를 기록하고 지운다. sites_lock 안에서 부른다."""
    s = sites.get(key)
    if s is None:
        return
    uri, line, col = key
    word, ltxt = word_at(text, line, col)
    done = bool(word) and (force or s["away"] or col + len(word) < len(ltxt))
    if not done and not (force or (s["away"] and not word)):
        return
    sites.pop(key)
    if not word:
        return
    name = os.path.basename(uri)
    with open(STATS, "a") as f:
        for typed_len, orders in sorted(s["levels"].items()):
            rank = {k: (o.index(word) + 1 if word in o else None) for k, o in orders.items()}
            f.write(json.dumps({"t": int(s["t"]), "file": name, "line": line, "typed": typed_len, "gold": word,
                                "n": len(orders["clangd"]), "rank": rank}) + "\n")


def sites_on_change(uri, changes):
    """didChange 반영 전에 자리 위치를 옮기고, 반영 후 끝난 자리를 기록한다."""
    if not STATS:
        return apply_change(uri, changes)
    with sites_lock:
        pre = docs.get(uri, "")
        for key in [k for k in sites if k[0] == uri]:
            s = sites.pop(key)
            line, col = key[1], key[2]
            wend = col + len(word_at(pre, line, col)[0])
            for ch in changes:
                if "range" not in ch:
                    s["away"] = True
                    continue
                st, en = ch["range"]["start"], ch["range"]["end"]
                nl = ch["text"].count("\n")
                if en["line"] < line:  # 윗줄 편집: 줄 번호만 옮긴다
                    line += nl - (en["line"] - st["line"])
                elif en["line"] == line and en["character"] < col:  # 같은 줄, 단어 앞 편집
                    tail = len(ch["text"].rsplit("\n", 1)[-1]) if nl else st["character"] + len(ch["text"])
                    col = tail + (col - en["character"])
                    line = st["line"] + nl
                elif st["line"] == line == en["line"] and col <= st["character"] <= wend + 1:
                    pass  # 그 단어를 치고 있다 (완성 항목 삽입 포함)
                else:
                    s["away"] = True
            sites[(uri, line, col)] = s
        apply_change(uri, changes)
        text = docs.get(uri, "")
        now = time.time()
        for key in [k for k in sites if k[0] == uri]:
            site_close(key, text, force=now - sites[key]["t"] > 120)


def sites_flush(uri, force=False, line=None, ch=None):
    """새 completion 요청·저장·닫기 때: 다른 자리의 끝난 단어를 기록한다."""
    if not STATS:
        return
    with sites_lock:
        text = docs.get(uri, "")
        for key in [k for k in sites if k[0] == uri]:
            if line is not None and key[1] == line and key[2] <= ch <= key[2] + len(word_at(text, key[1], key[2])[0]) + 1:
                continue  # 같은 단어 자리의 다음 글자 요청
            sites[key]["away"] = True
            site_close(key, text, force=force)


def editor_to_clangd(editor_in, clangd_in):
    while True:
        msg = read_msg(editor_in)
        if msg is None:
            break
        m = msg.get("method")
        p = msg.get("params", {})
        try:
            if m == "textDocument/didOpen":
                docs[p["textDocument"]["uri"]] = p["textDocument"]["text"]
            elif m == "textDocument/didChange":
                sites_on_change(p["textDocument"]["uri"], p["contentChanges"])
            elif m == "textDocument/didSave":
                sites_flush(p["textDocument"]["uri"], force=True)
            elif m == "textDocument/didClose":
                sites_flush(p["textDocument"]["uri"], force=True)
                docs.pop(p["textDocument"]["uri"], None)
            elif m == "textDocument/completion":
                sites_flush(p["textDocument"]["uri"], line=p["position"]["line"], ch=p["position"]["character"])
                pending[msg["id"]] = (p["textDocument"]["uri"], p["position"]["line"], p["position"]["character"])
        except Exception as e:  # 추적 실패는 재정렬만 포기하고 통신은 계속
            log(f"track error: {e}")
        write_msg(clangd_in, msg)


def clangd_to_editor(clangd_out, editor_out):
    while True:
        msg = read_msg(clangd_out)
        if msg is None:
            break
        key = msg.get("id")
        if key in pending and "result" in msg:
            uri, line, ch = pending.pop(key)
            res = msg["result"]
            items = (res.get("items") if isinstance(res, dict) else res) or []
            try:
                state = state_for(uri, line, ch)
            except Exception as e:
                state, items = None, []
                log(f"state error: {e}")
            gens = []
            if state is not None and GEN_URL and decl_site(state):
                try:  # 선언 자리: 재정렬 대신 이름 생성 (clangd 후보는 보통 비었거나 무관하다)
                    typed = typed_prefix(state)
                    gens = generate_names(state, typed, {it.get("filterText") or it["label"].strip() for it in items})
                except Exception as e:
                    log(f"gen skipped: {type(e).__name__} {e}")
            elif items:
                try:
                    new, info = rerank(items, state)
                    site_open(uri, line, ch, info)
                    if new is not None:
                        if isinstance(res, dict):
                            res["items"] = new
                        else:
                            msg["result"] = new
                except Exception as e:  # 시간 초과 등: clangd 순서 그대로
                    log(f"rerank skipped: {type(e).__name__} {e}")
            if gens:
                if isinstance(res, dict):
                    res["items"] = gen_items(gens) + list(res.get("items") or [])
                else:
                    msg["result"] = {"isIncomplete": False, "items": gen_items(gens) + list(res or [])}
        write_msg(editor_out, msg)


def main():
    clangd = subprocess.Popen([os.environ.get("CLANGD_BIN", "clangd")] + sys.argv[1:],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    editor_in, editor_out = sys.stdin.buffer, sys.stdout.buffer
    t = threading.Thread(target=clangd_to_editor, args=(clangd.stdout, editor_out), daemon=True)
    t.start()
    editor_to_clangd(editor_in, clangd.stdin)
    clangd.terminate()


if __name__ == "__main__":
    main()
