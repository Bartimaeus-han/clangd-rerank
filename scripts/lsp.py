import json, subprocess, sys, os
args = sys.argv[1:]
d = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(d, "test.cpp")).read()
uri = "file://" + os.path.join(d, "test.cpp")
p = subprocess.Popen(["/usr/bin/clangd", "--log=error"] + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
def send(m):
    b = json.dumps(m).encode()
    p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); p.stdin.flush()
def recv():
    h = {}
    while True:
        l = p.stdout.readline().decode().strip()
        if not l: break
        k, v = l.split(":", 1); h[k] = v
    return json.loads(p.stdout.read(int(h["Content-Length"])))
def wait(i):
    while True:
        m = recv()
        if m.get("id") == i: return m
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"processId":None,"rootUri":None,"capabilities":{}}})
wait(1)
send({"jsonrpc":"2.0","method":"initialized","params":{}})
send({"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{"uri":uri,"languageId":"cpp","version":1,"text":src}}})
while recv().get("method") != "textDocument/publishDiagnostics": pass
send({"jsonrpc":"2.0","id":2,"method":"textDocument/completion","params":{"textDocument":{"uri":uri},"position":{"line":4,"character":4}}})
r = wait(2)["result"]
items = r["items"] if isinstance(r, dict) else r
for it in sorted(items, key=lambda x: x["sortText"])[:8]:
    print(f'{it["score"]:.6g}\t{it["label"].strip()}')
p.kill()
