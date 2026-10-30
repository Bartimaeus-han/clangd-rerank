"""LSP 프록시 동작 확인: 프록시를 에디터처럼 띄워 completion을 요청하고, 재정렬 전후 상위 5개를 비교한다.

사용: proxy_smoke.py <file.cpp> <line> <character>   (환경 변수는 clangd_rerank_proxy.py 와 같다)
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def session(cmd, path, line, ch):
    uri = "file://" + os.path.abspath(path)
    src = open(path).read()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def send(m):
        b = json.dumps(m).encode()
        p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b)
        p.stdin.flush()

    def recv():
        h = {}
        while True:
            l = p.stdout.readline().decode().strip()
            if not l:
                break
            k, v = l.split(":", 1)
            h[k.strip().lower()] = v
        return json.loads(p.stdout.read(int(h["content-length"])))

    def wait(i):
        while True:
            m = recv()
            if m.get("id") == i:
                return m

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"processId": None, "rootUri": None, "capabilities": {}}})
    wait(1)
    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "languageId": "cpp", "version": 1, "text": src}}})
    while recv().get("method") != "textDocument/publishDiagnostics":
        pass
    t0 = time.perf_counter()
    send({"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion", "params": {"textDocument": {"uri": uri}, "position": {"line": line, "character": ch}}})
    r = wait(2)["result"]
    ms = (time.perf_counter() - t0) * 1000
    p.kill()
    items = r["items"] if isinstance(r, dict) else r
    return [it["label"].strip() for it in sorted(items, key=lambda x: x["sortText"])][:5], ms


def main():
    path, line, ch = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    plain, ms1 = session(["clangd", "--log=error"], path, line, ch)
    cmd = os.environ.get("PROXY_CMD")  # 확장이 만드는 런처 스크립트 등을 그대로 시험할 때
    proxied, ms2 = session(([cmd] if cmd else [sys.executable, os.path.join(HERE, "clangd_rerank_proxy.py")]) + ["--log=error"], path, line, ch)
    print(f"clangd 그대로 ({ms1:.0f}ms): {plain}")
    print(f"프록시 거침  ({ms2:.0f}ms): {proxied}")


if __name__ == "__main__":
    main()
