"""clangd 후보를 Jev Choice로 재정렬하는 스모크 테스트.

사용: rerank_smoke.py <file.cpp> <line(0-based)> <character(0-based)>
"""
import json, os, subprocess, sys, time

from typesafe_sdk import Choice, TypeSafeClient


def clangd_candidates(path, line, character):
    uri = "file://" + os.path.abspath(path)
    src = open(path).read()
    p = subprocess.Popen(["/usr/bin/clangd", "--log=error"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

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
            h[k] = v
        return json.loads(p.stdout.read(int(h["Content-Length"])))

    def wait(i):
        while True:
            m = recv()
            if m.get("id") == i:
                return m

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"processId": None, "rootUri": None, "capabilities": {}}})
    wait(1)
    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": uri, "languageId": "cpp", "version": 1, "text": src}}})
    while recv().get("method") != "textDocument/publishDiagnostics":
        pass
    send({"jsonrpc": "2.0", "id": 2, "method": "textDocument/completion", "params": {
        "textDocument": {"uri": uri}, "position": {"line": line, "character": character}}})
    r = wait(2)["result"]
    p.kill()
    items = r["items"] if isinstance(r, dict) else r
    # 오버로드는 이름 하나로 묶는다. clangd 순서(sortText)에서 처음 나온 위치를 그 이름의 순위로 쓴다.
    by_name = {}
    for it in sorted(items, key=lambda x: x["sortText"]):
        name = it.get("filterText") or it["label"].strip()
        if name not in by_name:
            by_name[name] = {"name": name, "detail": (it.get("label", "").strip() + " -> " + it.get("detail", "")).strip(),
                             "score": it["score"]}
    return list(by_name.values()), src


def state_with_cursor(src, line, character):
    lines = src.split("\n")
    lines[line] = lines[line][:character] + "<CURSOR>" + lines[line][character:]
    return "\n".join(lines)


def main():
    path, line, character = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    cands, src = clangd_candidates(path, line, character)
    cands = cands[:255]
    print(f"clangd 후보 {len(cands)}개, 상위 5개(clangd 순서):")
    for c in cands[:5]:
        print(f"  {c['score']:.4f}  {c['name']}")

    client = TypeSafeClient()
    t0 = time.perf_counter()
    resp = client.system_one(
        state=state_with_cursor(src, line, character),
        questions={"next": Choice(
            instructions="C++ code with a <CURSOR> marker. Which identifier will the programmer most likely type at <CURSOR>?",
            criteria={c["name"]: c["detail"] for c in cands},
        )},
    )
    ms = (time.perf_counter() - t0) * 1000
    ans = resp.answers["next"]
    probs = sorted(ans.probabilities.items(), key=lambda kv: -kv[1])
    print(f"\nJev ({resp.model}, {ms:.0f}ms 왕복) 선택: {ans.choice}, confidence {ans.confidence:.3f}")
    print("Jev 상위 5개:")
    for name, pr in probs[:5]:
        rank = next(i for i, c in enumerate(cands) if c["name"] == name) + 1
        print(f"  {pr:.3f}  {name}  (clangd {rank}위)")
    print(f"usage: {resp.usage}")


if __name__ == "__main__":
    main()
