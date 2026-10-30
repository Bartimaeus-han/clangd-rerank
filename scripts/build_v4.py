"""v4 학습셋 구성: 응용 저장소 샘플(train_out3)을 편향 규칙에 따라 고른다.

사용: build_v4.py <train_out3> <app_test_pick.json> <out_sel_dir> <out_test_dir>
규칙 (사용자 지시: 데이터 편향 주의):
  - 시험셋 저장소(주제별 1개)는 학습에서 완전히 뺀다 → <out_test_dir>/samples.jsonl (모든 위치).
  - 시험용 라이브러리(fmt, CLI11, lz4, entt, cxxopts)가 번들된 파일, 다른 저장소에 복사된 같은 파일(내용 해시 중복)은 뺀다.
  - 프로젝트당 위치 상한 CAP(기본 100, 무작위·고정 시드), codecontests 는 CC_CAP(기본 1000).
  - 결과: <out_sel_dir>/<프로젝트>/samples.jsonl, sources.txt(경로 목록), summary.txt(주제별 집계).
"""
import collections, hashlib, json, os, random, re, sys

root, pick_path, out_sel, out_test = [os.path.abspath(a) for a in sys.argv[1:5]]
CAP = int(os.environ.get("CAP", "100"))
CC_CAP = int(os.environ.get("CC_CAP", "1000"))
SEED = int(os.environ.get("SEED", "0"))
SRC_ROOT = os.path.abspath(os.environ.get("TRAIN_SRC", os.path.expanduser("~/work/clangd-rerank/train_src2")))  # samples 의 file 은 프로젝트 상대 경로
TEST_LIBS = re.compile(r"(^|/)(fmt/|format\.(h|cc)|CLI11?\.hpp|CLI/|lz4(hc|frame)?\.(c|h)|entt(/|\.hpp)|cxxopts\.hpp)", re.I)

tests = set(json.load(open(pick_path)).values())
os.makedirs(out_sel, exist_ok=True)
os.makedirs(out_test, exist_ok=True)
rng = random.Random(SEED)
seen_hash = {}
stats = collections.defaultdict(lambda: collections.Counter())
dropped = collections.Counter()
sources = []
test_out = open(os.path.join(out_test, "samples.jsonl"), "w")
n_test = 0
for d in sorted(os.listdir(root)):
    p = os.path.join(root, d, "samples.jsonl")
    if not os.path.exists(p):
        continue
    topic = d.split("__")[0]
    samples = [json.loads(l) for l in open(p)]
    for s in samples:
        s["project"] = d
    if d in tests:
        for s in samples:
            test_out.write(json.dumps(s) + "\n")
        n_test += len(samples)
        stats[topic]["test_pos"] += len(samples)
        stats[topic]["test_proj"] += 1
        continue
    kept = []
    for s in samples:
        f = os.path.join(SRC_ROOT, d, s["file"])
        if TEST_LIBS.search(s["file"]):
            dropped["test_lib_file"] += 1
            continue
        if f not in seen_hash:
            try:
                seen_hash[f] = hashlib.sha1(open(f, "rb").read()).hexdigest()
            except OSError:
                seen_hash[f] = None
        h = seen_hash[f]
        key = ("h", h)
        owner = seen_hash.setdefault(key, d)
        if h is not None and owner != d:  # 다른 저장소에 같은 내용의 파일이 이미 있음 (번들 복사본)
            dropped["dup_file"] += 1
            continue
        kept.append(s)
    cap = CC_CAP if topic == "codecontests" else CAP
    if len(kept) > cap:
        rng.shuffle(kept)
        dropped["over_cap"] += len(kept) - cap
        kept = sorted(kept[:cap], key=lambda s: (s["file"], s["line"], s["col"]))
    if not kept:
        continue
    od = os.path.join(out_sel, d)
    os.makedirs(od, exist_ok=True)
    with open(os.path.join(od, "samples.jsonl"), "w") as f:
        for s in kept:
            f.write(json.dumps(s) + "\n")
    sources.append(os.path.join(od, "samples.jsonl"))
    st = stats[topic]
    st["proj"] += 1
    st["pos"] += len(kept)
    for s in kept:
        st[s.get("kind", "ident")] += 1
test_out.close()
open(os.path.join(out_sel, "sources.txt"), "w").write("\n".join(sources) + "\n")
lines = [f"{'주제':<19}{'학습proj':>8}{'위치':>7}{'member%':>9}{'scope%':>8}{'시험proj':>9}{'시험위치':>9}"]
tot = collections.Counter()
for t, st in sorted(stats.items(), key=lambda x: -x[1]["pos"]):
    n = st["pos"]
    lines.append(f"{t:<19}{st['proj']:>8}{n:>7}{100*st['member']/max(1,n):>9.1f}{100*st['scope']/max(1,n):>8.1f}{st['test_proj']:>9}{st['test_pos']:>9}")
    tot.update(st)
n = tot["pos"]
lines.append(f"합계 학습 {tot['proj']}프로젝트 {n}위치 (member {100*tot['member']/max(1,n):.1f}%, scope {100*tot['scope']/max(1,n):.1f}%); 시험 {tot['test_proj']}프로젝트 {n_test}위치")
lines.append(f"제외: 시험 라이브러리 파일 {dropped['test_lib_file']}, 중복 파일 {dropped['dup_file']}, 상한 초과 {dropped['over_cap']} (CAP={CAP}, CC_CAP={CC_CAP}, SEED={SEED})")
open(os.path.join(out_sel, "summary.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
