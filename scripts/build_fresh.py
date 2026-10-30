"""신선 시험셋(기반 모델 공개 이후 생긴 저장소) 구성: collect_auto.py 출력에서 편향·중복 규칙을 적용해 고른다.

사용: build_fresh.py <fresh_out_root> <out_dir> <train_src_root> [<train_src_root> ...]
규칙 (build_v4.py 와 같은 취지):
  - 시험용 라이브러리(fmt, CLI11, lz4, entt, cxxopts)가 번들된 파일은 뺀다.
  - 학습 소스 트리(train_src, train_src2)에 내용이 같은 파일이 있으면 뺀다(복사본 → 모델이 학습 때 본 코드).
  - 주제당 위치 상한 CAP(기본 90, 무작위·고정 시드) — eval_app_sub 와 같은 모양.
  - 결과: <out_dir>/samples.jsonl ("project" 필드 추가), <out_dir>/summary.txt (주제별 집계).
"""
import collections, hashlib, json, os, random, re, sys

root, out_dir, train_roots = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), [os.path.abspath(a) for a in sys.argv[3:]]
CAP = int(os.environ.get("CAP", "90"))
SEED = int(os.environ.get("SEED", "0"))
SRC_ROOT = os.path.abspath(os.environ.get("FRESH_SRC", os.path.expanduser("~/work/clangd-rerank/eval_src_fresh")))
TEST_LIBS = re.compile(r"(^|/)(fmt/|format\.(h|cc)|CLI11?\.hpp|CLI/|lz4(hc|frame)?\.(c|h)|entt(/|\.hpp)|cxxopts\.hpp)", re.I)
EXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".inl", ".ipp")


def sha1(p):
    try:
        return hashlib.sha1(open(p, "rb").read()).hexdigest()
    except OSError:
        return None


train_hashes = set()
for tr in train_roots:
    for dp, dns, fns in os.walk(tr):
        dns[:] = [d for d in dns if d != ".git"]
        for fn in fns:
            if fn.endswith(EXT):
                h = sha1(os.path.join(dp, fn))
                if h:
                    train_hashes.add(h)
print(f"학습 소스 파일 해시 {len(train_hashes)}개", flush=True)

rng = random.Random(SEED)
by_topic = collections.defaultdict(list)
stats = collections.defaultdict(collections.Counter)
dropped = collections.Counter()
for d in sorted(os.listdir(root)):
    p = os.path.join(root, d, "samples.jsonl")
    if not os.path.exists(p):
        continue
    topic = d.split("__")[0]
    kept = []
    for l in open(p):
        s = json.loads(l)
        s["project"] = d
        if TEST_LIBS.search(s["file"]):
            dropped["test_lib_file"] += 1
            continue
        if sha1(os.path.join(SRC_ROOT, d, s["file"])) in train_hashes:
            dropped["dup_with_train"] += 1
            continue
        kept.append(s)
    if kept:
        by_topic[topic].extend(kept)
        stats[topic]["proj"] += 1
        stats[topic]["raw"] += len(kept)

os.makedirs(out_dir, exist_ok=True)
sub = []
for t, ss in sorted(by_topic.items()):
    rng.shuffle(ss)
    pick = sorted(ss[:CAP], key=lambda s: (s["project"], s["file"], s["line"], s["col"]))
    dropped["over_cap"] += max(0, len(ss) - CAP)
    sub += pick
    st = stats[t]
    st["pos"] = len(pick)
    for s in pick:
        st[s.get("kind", "ident")] += 1
with open(os.path.join(out_dir, "samples.jsonl"), "w") as f:
    for s in sub:
        f.write(json.dumps(s) + "\n")

lines = [f"{'주제':<19}{'proj':>5}{'유효위치':>8}{'채택':>6}{'member%':>9}{'scope%':>8}"]
tot = collections.Counter()
for t, st in sorted(stats.items(), key=lambda x: -x[1]["pos"]):
    n = st["pos"]
    lines.append(f"{t:<19}{st['proj']:>5}{st['raw']:>8}{n:>6}{100*st['member']/max(1,n):>9.1f}{100*st['scope']/max(1,n):>8.1f}")
    tot.update(st)
n = tot["pos"]
lines.append(f"합계 {tot['proj']}프로젝트 {len(by_topic)}주제 유효 {tot['raw']}위치 → 채택 {n}위치 (member {100*tot['member']/max(1,n):.1f}%, scope {100*tot['scope']/max(1,n):.1f}%)")
lines.append(f"제외: 시험 라이브러리 파일 {dropped['test_lib_file']}, 학습 소스와 내용 중복 {dropped['dup_with_train']}, 상한 초과 {dropped['over_cap']} (CAP={CAP}, SEED={SEED})")
open(os.path.join(out_dir, "summary.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
