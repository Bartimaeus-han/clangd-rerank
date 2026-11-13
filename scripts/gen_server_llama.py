#!/usr/bin/env python3
"""Namer 서버 — llama.cpp(llama-cpp-python 저수준 API) 판. gen_server.py(HF transformers)와 같은 HTTP 형식.

사용: <llama venv>/bin/python scripts/gen_server_llama.py --gguf <모델.gguf> [--port 8010] [--beams 3]
  POST /v1/gen  {"prefix": "<파일 시작~커서 앞 코드(친 글자 제외)>", "typed": "ab", "n": 3}  →  {"guesses": [...], "ms": 41}
  GET  /v1/models
필요: llama-cpp-python(CUDA 휠) + CUDA 런타임 라이브러리가 LD_LIBRARY_PATH 에 (scripts/run_namer_llama.sh 가 맞춰 준다).

생성 방식 (2026-11-13 디코딩 실험에서 HF beam3 보다 정확도가 같거나 높고 계산이 3분의 1):
  - 이름 단위 빔 탐색(W=3): 가설이 '이름 끝'(식별자 글자가 아닌 토큰)에 닿으면 바로 끝난 후보로 넘기고, 점수는
    P(이름) × P(경계)(경계 = 식별자 글자로 시작하지 않는 모든 토큰의 확률 합). 같은 이름은 확률을 합친다.
  - 토큰 치유: 프롬프트가 홑 공백으로 끝나면(`std::string ` 등, 92%) 그 공백을 떼고 첫 토큰이 ' '+식별자 글자로 시작하게 한다
    (BPE 는 ` count` 처럼 공백을 붙여 쓰므로).
  - 친 글자 제약: 이름이 친 글자로 시작해야 한다. 토큰 경계를 넘는 경우(`co` + `unt`)도 글자 단위로 맞춘다.
    허용 토큰 마스크는 정렬된 토큰 표의 이분 탐색으로 만들고 (남은 글자, 첫 토큰 여부) 별로 캐시한다.
  - 키워드는 뺀다. 첫 글자가 숫자인 이름은 막는다.
  - 프롬프트 KV 재사용: 0번 시퀀스에 마지막 프롬프트를 두고, 다음 요청은 공통 접두 뒤만 계산한다
    (같은 자리에서 글자를 칠 때마다 프롬프트가 같으므로 사실상 prefill 이 사라진다). 빔은 1..2W 번 시퀀스에 복사해 쓴다.
"""
import argparse, bisect, collections, ctypes, json, math, os, re, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_rerank import KEYWORDS  # noqa: E402
from ctx_enrich import build_prompt  # noqa: E402

import llama_cpp as L  # noqa: E402

IDC = re.compile(r"[A-Za-z0-9_]*")
IDENT = re.compile(r"^[A-Za-z_]\w*$")
NEG = -1e30


class View:
    """토큰 표 한 벌. first=True 는 첫 토큰용(앞 홑 공백을 뗀 글자로 본다)."""

    def __init__(self, pieces, lead, special, first):
        n = len(pieces)
        ip, term = [], np.zeros(n, bool)
        for t, v in enumerate(pieces):
            if special[t] or v == "":
                ip.append(""); term[t] = True; continue
            b = v[1:] if (first and lead[t]) else v
            m = IDC.match(b).group(0)
            ip.append(m); term[t] = len(m) < len(b)
        self.ip = ip
        self.term = term
        self.nonempty = np.array([bool(x) for x in ip])
        self.digit0 = np.array([bool(x) and x[0].isdigit() for x in ip])
        order = sorted(range(n), key=lambda t: ip[t])
        self.order = np.array(order, dtype=np.int64)
        self.sorted_ip = [ip[t] for t in order]
        self.by_ip = {}
        for t, x in enumerate(ip):
            if x:
                self.by_ip.setdefault(x, []).append(t)

    def starts_with(self, rem):
        """ip 가 rem 으로 시작하는 토큰 id 배열 (정렬 표의 연속 구간)."""
        lo = bisect.bisect_left(self.sorted_ip, rem)
        hi = bisect.bisect_left(self.sorted_ip, rem + "\U0010ffff")
        return self.order[lo:hi]


class Namer:
    def __init__(self, gguf, beams=3, max_tokens=8, ctx=40, enrich=True, n_ctx=4096, heal=True):
        self.W, self.maxt, self.ctx_lines, self.enrich, self.heal = beams, max_tokens, ctx, enrich, heal
        L.llama_backend_init()
        mp = L.llama_model_default_params()
        mp.n_gpu_layers = 999
        self.model = L.llama_model_load_from_file(gguf.encode(), mp)
        if not self.model:
            raise SystemExit(f"모델을 못 읽음: {gguf}")
        cp = L.llama_context_default_params()
        cp.n_ctx = n_ctx
        cp.n_batch = 2048
        cp.n_ubatch = 512
        cp.n_seq_max = 1 + 2 * beams
        cp.kv_unified = True      # 시퀀스 복사가 셀 공유(메타데이터)로 끝나게
        cp.flash_attn_type = L.LLAMA_FLASH_ATTN_TYPE_AUTO
        cp.no_perf = True
        self.n_ctx = n_ctx
        self.ctx = L.llama_init_from_model(self.model, cp)
        if not self.ctx:
            raise SystemExit("컨텍스트를 못 만듦")
        self.mem = L.llama_get_memory(self.ctx)
        self.vocab = L.llama_model_get_vocab(self.model)
        self.V = L.llama_vocab_n_tokens(self.vocab)
        self.batch = L.llama_batch_init(2048, 0, 1)
        pieces, special = [], []
        buf = ctypes.create_string_buffer(256)
        for t in range(self.V):
            k = L.llama_token_to_piece(self.vocab, t, buf, 256, 0, False)
            pieces.append(buf.raw[:k].decode("utf-8", errors="replace") if k > 0 else "")
            special.append(bool(L.llama_vocab_is_control(self.vocab, t)) or bool(L.llama_vocab_is_eog(self.vocab, t)))
        lead = [v.startswith(" ") and not v.startswith("  ") for v in pieces]
        self.lead = np.array(lead)
        self.first = View(pieces, lead, special, True)
        self.later = View(pieces, lead, special, False)
        self.pure_term = ~self.later.nonempty  # 식별자 글자로 시작하지 않는 토큰 (경계)
        self.pure_idx = np.flatnonzero(self.pure_term)
        self.ALL = np.ones(self.V, bool)  # '제약 없음' 표시 (np.where 생략)
        self.masks = collections.OrderedDict()  # (남은 글자, 첫 토큰, 치유) -> 허용 토큰 bool 배열, 최근 512개만
        self.cache_tokens = []  # 0번 시퀀스에 들어 있는 프롬프트
        self.lock = threading.Lock()

    # ---- 토큰·배치 ----
    def tokenize(self, text):
        b = text.encode("utf-8")
        n = len(b) + 16
        arr = (L.llama_token * n)()
        k = L.llama_tokenize(self.vocab, b, len(b), arr, n, False, True)
        if k < 0:
            arr = (L.llama_token * (-k))()
            k = L.llama_tokenize(self.vocab, b, len(b), arr, -k, False, True)
        return list(arr[:k])

    def _decode(self, items):
        """items: [(token, pos, seq, want_logits)] → 로짓이 필요한 항목의 배치 안 번호 목록."""
        out = []
        for start in range(0, len(items), 2048):
            chunk = items[start:start + 2048]
            b = self.batch
            b.n_tokens = len(chunk)
            for i, (tok, pos, seq, want) in enumerate(chunk):
                b.token[i] = tok; b.pos[i] = pos; b.n_seq_id[i] = 1; b.seq_id[i][0] = seq; b.logits[i] = want
            rc = L.llama_decode(self.ctx, b)
            if rc != 0:
                raise RuntimeError(f"llama_decode 실패 {rc}")
            out += [i for i, it in enumerate(chunk) if it[3]]
        return out

    def _logprobs(self, i):
        """(log-prob 행 float32, 경계 log-prob = 식별자 글자로 시작하지 않는 토큰들의 확률 합의 log)"""
        p = L.llama_get_logits_ith(self.ctx, i)
        x = np.ctypeslib.as_array(p, shape=(self.V,))
        m = float(x.max())
        e = np.exp(x - m)
        lse = m + math.log(float(e.sum()))
        bnd = math.log(max(float(e[self.pure_idx].sum()), 1e-300)) + m - lse
        return x - np.float32(lse), bnd

    def _prefill(self, toks):
        """0번 시퀀스를 toks 로 맞추고 마지막 토큰의 log-prob 을 돌려준다. 공통 접두는 다시 계산하지 않는다."""
        for s in range(1, 1 + 2 * self.W):
            L.llama_memory_seq_rm(self.mem, s, -1, -1)
        p = 0
        old = self.cache_tokens
        while p < len(old) and p < len(toks) and old[p] == toks[p]:
            p += 1
        p = min(p, len(toks) - 1)  # 마지막 토큰은 로짓을 받으려고 늘 다시 넣는다 (toks 는 비어 있지 않다)
        if not L.llama_memory_seq_rm(self.mem, 0, p, -1):
            L.llama_memory_seq_rm(self.mem, 0, -1, -1); p = 0
        self.cache_tokens = list(toks[:p])  # 실패해도 0번 시퀀스와 어긋나지 않게 먼저 맞춘다
        items = [(t, p + j, 0, False) for j, t in enumerate(toks[p:])]
        items[-1] = (items[-1][0], items[-1][1], 0, True)
        try:
            idx = self._decode(items)
        except Exception:
            L.llama_memory_seq_rm(self.mem, -1, -1, -1)  # 모든 시퀀스 비우고 처음부터
            self.cache_tokens = []
            raise
        self.cache_tokens = list(toks)
        return self._logprobs(idx[-1]), len(toks) - p

    # ---- 마스크 ----
    def mask_for(self, s, typed, first, heal):
        rem = typed[len(s):] if typed.startswith(s) else None
        key = (rem, first, heal and first)  # 치유는 첫 토큰에만 영향
        m = self.masks.get(key)
        if m is not None:
            self.masks.move_to_end(key)
            return m
        vw = self.first if first else self.later
        if rem is None and not first:  # 이미 친 글자를 다 넘었다: 제약 없음
            return self.ALL
        if rem is None:
            m = np.ones(self.V, bool)
        else:
            m = np.zeros(self.V, bool)
            m[vw.starts_with(rem)] = True               # 덧붙는 글자가 rem 으로 시작 (끝나는 토큰 포함)
            for j in range(1, len(rem)):               # 아직 rem 의 앞부분만 채우는 토큰 (끝나면 안 됨)
                for t in vw.by_ip.get(rem[:j], ()):
                    if not vw.term[t]:
                        m[t] = True
            if rem == "":                              # 다 채웠다: 이어지는 토큰은 글자가 있어야
                m &= vw.nonempty | vw.term
        if first:
            m &= vw.nonempty & ~vw.digit0
            if heal:
                m &= self.lead
        self.masks[key] = m
        if len(self.masks) > 512:
            self.masks.popitem(last=False)
        return m

    # ---- 생성 ----
    @staticmethod
    def _ok(n, typed):
        return bool(n) and IDENT.match(n) is not None and n.startswith(typed) and n not in KEYWORDS

    def generate(self, prefix, typed, n):
        prompt = build_prompt("\n".join(prefix.split("\n")[-3000:]), self.ctx_lines, self.enrich)
        heal = False
        if self.heal and prompt.endswith(" ") and len(prompt) > 1 and not prompt[-2].isspace():
            prompt, heal = prompt[:-1], True
        toks = self.tokenize(prompt)
        if not toks:
            return [], 0.0, {"passes": 0, "prompt_tok": 0, "new_tok": 0}
        if len(toks) > self.n_ctx - self.maxt * 2 * self.W - 8:
            toks = toks[-(self.n_ctx - self.maxt * 2 * self.W - 8):]
        W, fin = self.W, {}

        def add(name, sc):
            fin[name] = sc if name not in fin else float(np.logaddexp(fin[name], sc))

        with self.lock:
            t0 = time.perf_counter()
            row0, new_tok = self._prefill(toks)
            rows = [row0]
            live = [("", 0.0, 0)]       # (이름 조각, 누적 점수, 시퀀스)
            npos = len(toks)
            sets = [list(range(1, 1 + W)), list(range(1 + W, 1 + 2 * W))]
            passes = 1
            for step in range(self.maxt):
                first = step == 0
                vw = self.first if first else self.later
                cand = []
                for r, (s, cum, _) in enumerate(live):
                    row, bnd = rows[r]
                    if not first and self._ok(s, typed):
                        add(s, cum + bnd)
                    m = self.mask_for(s, typed, first, heal)
                    sc = row if m is self.ALL else np.where(m, row, np.float32(NEG))
                    k = min(4 * W, self.V if m is self.ALL else int(m.sum()))
                    if k <= 0:
                        continue
                    top = np.argpartition(-sc, k - 1)[:k]
                    for t in top[np.argsort(-sc[top])]:
                        v = float(sc[t])
                        if v <= NEG / 2:
                            break
                        ip, term = vw.ip[t], bool(vw.term[t])
                        if term:
                            if ip and self._ok(s + ip, typed):
                                add(s + ip, cum + v)
                        else:
                            cand.append((cum + v, r, int(t), s + ip))
                cand.sort(key=lambda x: -x[0])
                nl, seen = [], set()
                for c in cand:
                    if c[3] in seen:
                        continue
                    seen.add(c[3]); nl.append(c)
                    if len(nl) == W:
                        break
                best = sorted(fin.values(), reverse=True)
                if not nl or (len(best) >= W and best[W - 1] >= nl[0][0]) or step == self.maxt - 1:
                    break
                # 자식 가설: 부모 시퀀스를 새 시퀀스로 복사하고 다음 토큰 하나씩
                tgt = sets[step % 2]
                for sid in tgt:
                    L.llama_memory_seq_rm(self.mem, sid, -1, -1)
                items = []
                for j, (score, r, t, s2) in enumerate(nl):
                    L.llama_memory_seq_cp(self.mem, live[r][2], tgt[j], -1, -1)
                    items.append((t, npos, tgt[j], True))
                idx = self._decode(items)
                passes += 1
                if step > 0:
                    for sid in sets[(step + 1) % 2]:
                        L.llama_memory_seq_rm(self.mem, sid, -1, -1)
                rows = [self._logprobs(i) for i in idx]
                live = [(c[3], c[0], tgt[j]) for j, c in enumerate(nl)]
                npos += 1
            res = sorted(fin.items(), key=lambda x: -x[1])
            ms = (time.perf_counter() - t0) * 1000
            return [nm for nm, _ in res][:n], ms, {"passes": passes, "prompt_tok": len(toks), "new_tok": new_tok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True); ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--beams", type=int, default=3); ap.add_argument("--max-tokens", type=int, default=8)
    ap.add_argument("--ctx", type=int, default=40); ap.add_argument("--n-ctx", type=int, default=4096)
    ap.add_argument("--no-enrich", action="store_true"); ap.add_argument("--no-heal", action="store_true")
    a = ap.parse_args()
    g = Namer(a.gguf, a.beams, a.max_tokens, a.ctx, not a.no_enrich, a.n_ctx, not a.no_heal)
    for typed in ("", "c", "co"):  # 워밍업
        print("warmup", typed, g.generate("#include <string>\nint main() {\n  std::string ", typed, 3), flush=True)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            self._send(200, {"data": [{"id": "gen", "model": os.path.basename(a.gguf), "engine": "llama.cpp"}]})

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
                guesses, ms, info = g.generate(req.get("prefix", ""), req.get("typed", ""), int(req.get("n", 3)))
                print(f"{ms:6.0f}ms typed={req.get('typed', '')!r} new_tok={info['new_tok']} passes={info['passes']} -> {guesses[:3]}", flush=True)
                self._send(200, {"guesses": guesses, "ms": ms})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    print(f"gen server (llama.cpp) on 127.0.0.1:{a.port} ({os.path.basename(a.gguf)})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
