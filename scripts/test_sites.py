"""clangd_rerank_proxy.py 의 실사용 측정(sites) 로직 단위 시험. clangd 없이 함수만 부른다.
사용: python3 -I test_sites.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
stats = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False).name
os.environ["RERANK_STATS"] = stats
os.environ.pop("STAGE2_MODEL", None)
sys.path.insert(0, HERE)
import clangd_rerank_proxy as P

URI = "file:///x/a.cpp"


def change(line, c0, c1, text, l1=None):
    return {"range": {"start": {"line": line, "character": c0}, "end": {"line": l1 if l1 is not None else line, "character": c1}}, "text": text}


def info(typed, clangd, final):
    return {"typed": typed, "orders": {"clangd": clangd, "stage2": clangd, "final": final}}


def rows():
    return [json.loads(l) for l in open(stats)]


def reset():
    open(stats, "w").close()
    P.sites.clear(); P.docs.clear()


# 1) 0글자 요청 → 'push_back(' 삽입 → 바로 기록 ('(' 가 뒤따름)
reset()
P.docs[URI] = "int main() {\n  v.\n}\n"
P.site_open(URI, 1, 4, info("", ["size", "push_back", "begin"], ["push_back", "size", "begin"]))
P.sites_on_change(URI, [change(1, 4, 4, "push_back()")])
r = rows(); assert len(r) == 1 and r[0]["gold"] == "push_back" and r[0]["rank"] == {"clangd": 2, "stage2": 2, "final": 1}, r
assert not P.sites

# 2) 0글자 → 1글자('s') → 2글자('si') 요청이 한 묶음, 'size' 를 손으로 다 치고 ';' 입력 → 3줄 기록(typed 0,1,2)
reset()
P.docs[URI] = "  v.\n"
P.site_open(URI, 0, 4, info("", ["size", "push_back"], ["push_back", "size"]))
P.sites_on_change(URI, [change(0, 4, 4, "s")])
P.site_open(URI, 0, 5, info("s", ["size"], ["size"]))
P.sites_on_change(URI, [change(0, 5, 5, "i")])
P.site_open(URI, 0, 6, info("si", ["size"], ["size"]))
P.sites_on_change(URI, [change(0, 6, 6, "ze")])
assert rows() == [] and len(P.sites) == 1, (rows(), P.sites)
P.sites_on_change(URI, [change(0, 8, 8, ";")])
r = rows(); assert [x["typed"] for x in r] == [0, 1, 2] and r[0]["rank"]["final"] == 2 and r[1]["rank"]["final"] == 1, r

# 3) 윗줄에 줄을 넣어도 자리를 따라간다; 다른 곳 편집하면 단어 끝으로 간주해 기록
reset()
P.docs[URI] = "a\n  v.\nb\n"
P.site_open(URI, 1, 4, info("", ["size", "clear"], ["clear", "size"]))
P.sites_on_change(URI, [change(1, 4, 4, "clear")])
P.sites_on_change(URI, [change(0, 1, 1, "\nint x;")])   # 윗줄에 한 줄 추가 → 자리는 2번째 줄로
assert list(P.sites) == [(URI, 2, 4)], list(P.sites)
P.sites_on_change(URI, [change(3, 0, 0, "// ")])        # 다른 줄 편집 → away
r = rows(); assert len(r) == 1 and r[0]["gold"] == "clear" and r[0]["line"] == 2 and r[0]["rank"]["final"] == 1, r

# 4) 후보에 없는 식별자를 친 경우 rank None; 저장 때 강제 기록
reset()
P.docs[URI] = "  v.\n"
P.site_open(URI, 0, 4, info("", ["size"], ["size"]))
P.sites_on_change(URI, [change(0, 4, 4, "foo")])
assert rows() == []
P.sites_flush(URI, force=True)
r = rows(); assert len(r) == 1 and r[0]["gold"] == "foo" and r[0]["rank"]["final"] is None, r

# 5) 아무것도 안 치고 다른 곳으로 가면 기록 없이 버린다
reset()
P.docs[URI] = "  v.\nb\n"
P.site_open(URI, 0, 4, info("", ["size"], ["size"]))
P.sites_on_change(URI, [change(1, 0, 0, "x")])
assert rows() == [] and not P.sites

# 6) 다른 자리의 새 completion 요청이 오면 끝난 단어를 기록; 같은 단어 자리의 다음 글자 요청은 유지
reset()
P.docs[URI] = "  v.\n  w.\n"
P.site_open(URI, 0, 4, info("", ["size"], ["size"]))
P.sites_on_change(URI, [change(0, 4, 4, "s")])
P.sites_flush(URI, line=0, ch=5)       # 같은 자리 1글자 요청 → 유지
assert len(P.sites) == 1
P.sites_flush(URI, line=1, ch=4)       # 다른 자리 요청 → 기록
r = rows(); assert len(r) == 1 and r[0]["gold"] == "s" and r[0]["rank"]["final"] is None, r

# 7) 전체 교체(range 없음)도 깨지지 않는다
reset()
P.docs[URI] = "  v.\n"
P.site_open(URI, 0, 4, info("", ["size"], ["size"]))
P.sites_on_change(URI, [{"text": "  v.size()\n"}])
r = rows(); assert len(r) == 1 and r[0]["gold"] == "size" and r[0]["rank"]["final"] == 1, r

os.unlink(stats)
print("test_sites: 7개 통과")
