#!/usr/bin/env python3
"""식별자 생성 서버 (프로토타입). 선언 자리에서 커서 앞 문맥을 받아 새 이름 후보를 돌려준다.
사용: ext/kev/.venv/bin/python scripts/gen_server.py [--port 8010] [--model Qwen/Qwen3.5-0.8B-Base] [--adapter <LoRA 경로>] [--beams 5]
  POST /v1/gen  {"prefix": "<파일 시작~커서 앞 코드(친 글자 제외)>", "typed": "ab", "n": 3}  →  {"guesses": ["abort_flag", ...], "ms": 312}
  GET  /v1/models  (살아 있는지 확인)
디코딩은 gen_qwen.py 와 같되 한 가지를 고쳤다: 접두어가 없어도 첫 토큰은 식별자 시작 글자로 제한한다
(기반 모델 기준선에서 0글자 빈 응답 14% 의 원인이 `)` `0` 같은 토큰이 빔을 채우는 것이었다). 키워드는 뺀다.
프롬프트 = 마지막 --ctx 줄 + 그 앞부분의 선언 요약 한 줄(ctx_enrich.build_prompt, --no-enrich 로 끔).
HF generate 경로라 한 건 0.2~0.5초. 요청은 한 번에 하나씩 처리한다(락)."""
import argparse, json, os, re, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_rerank import KEYWORDS  # noqa: E402
from ctx_enrich import build_prompt  # noqa: E402

IDENT = re.compile(r"^[A-Za-z_]\w*")


class Generator:
    def __init__(self, model, adapter, beams, new_tokens, ctx, enrich=True):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model)
        lm = AutoModelForCausalLM.from_pretrained(model, dtype=torch.bfloat16)
        if adapter:
            from peft import PeftModel
            lm = PeftModel.from_pretrained(lm, adapter).merge_and_unload()
        self.lm = lm.cuda().eval()
        self.beams, self.new_tokens, self.ctx, self.enrich = beams, new_tokens, ctx, enrich
        vocab = [self.tok.decode([t]) for t in range(len(self.tok))]
        self.all_ids = list(range(len(self.tok)))
        self.vocab = vocab
        self.cache = {}
        self.lock = threading.Lock()

    def allowed_for(self, rem):
        """남은 접두어 rem 과 맞물리는 토큰. rem 이 비면 '식별자 시작 글자로 시작하는 토큰'."""
        if rem not in self.cache:
            if rem:
                ids = [t for t, v in enumerate(self.vocab) if (w := v.lstrip(" ")) and (w.startswith(rem) or rem.startswith(w))]
            else:
                ids = [t for t, v in enumerate(self.vocab) if (w := v.lstrip(" ")) and (w[0].isalpha() or w[0] == "_")]
            self.cache[rem] = ids or self.all_ids
        return self.cache[rem]

    def generate(self, prefix, typed, n):
        tok, torch = self.tok, self.torch
        # 마지막 ctx 줄은 그대로, 그 앞은 선언 요약 한 줄로 (ctx_enrich; 프록시가 파일 앞부분까지 보내준다)
        prompt = build_prompt("\n".join(prefix.split("\n")[-3000:]), self.ctx, self.enrich)
        with self.lock, torch.inference_mode():
            ids = tok(prompt, return_tensors="pt").input_ids.cuda()
            n_in = ids.shape[1]

            def prefix_fn(batch_id, seq):
                sofar = tok.decode(seq[n_in:], skip_special_tokens=True).lstrip(" ")
                if not sofar:
                    return self.allowed_for(typed)
                if sofar.startswith(typed):
                    return self.all_ids
                if typed.startswith(sofar):
                    return self.allowed_for(typed[len(sofar):])
                return self.allowed_for(typed)

            t0 = time.perf_counter()
            gen = self.lm.generate(ids, max_new_tokens=self.new_tokens, num_beams=self.beams, num_return_sequences=self.beams,
                                   do_sample=False, early_stopping=True, pad_token_id=tok.pad_token_id or tok.eos_token_id,
                                   prefix_allowed_tokens_fn=prefix_fn)
            out, seen = [], set()
            for g in gen:
                m = IDENT.match(tok.decode(g[n_in:], skip_special_tokens=True).lstrip())
                if m and m.group(0).startswith(typed) and m.group(0) not in KEYWORDS and m.group(0) not in seen:
                    seen.add(m.group(0)); out.append(m.group(0))
            torch.cuda.synchronize()
            return out[:n], (time.perf_counter() - t0) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010); ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B-Base")
    ap.add_argument("--adapter", default=""); ap.add_argument("--beams", type=int, default=5)
    ap.add_argument("--new-tokens", type=int, default=8); ap.add_argument("--ctx", type=int, default=40)
    ap.add_argument("--no-enrich", action="store_true", help="앞선 선언 요약(ctx_enrich)을 붙이지 않는다")
    a = ap.parse_args()
    g = Generator(a.model, a.adapter, a.beams, a.new_tokens, a.ctx, not a.no_enrich)
    for typed in ("", "c", "co"):  # 워밍업 (첫 요청 커널 컴파일)
        print("warmup", typed, g.generate("#include <string>\nint main() {\n  std::string ", typed, 3), flush=True)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 조용히
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            self._send(200, {"data": [{"id": "gen", "model": a.model, "adapter": a.adapter}]})

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
                guesses, ms = g.generate(req.get("prefix", ""), req.get("typed", ""), int(req.get("n", 3)))
                print(f"{ms:6.0f}ms typed={req.get('typed', '')!r} -> {guesses}", flush=True)
                self._send(200, {"guesses": guesses, "ms": ms})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    print(f"gen server on 127.0.0.1:{a.port} ({a.model}{' + ' + a.adapter if a.adapter else ''})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
