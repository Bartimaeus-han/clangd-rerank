"""프로젝트 폴더를 주면 컴파일 옵션(compile_flags.txt)과 파일 목록을 자동으로 정해 clangd 샘플을 모은다.

사용: collect_auto.py <out_root> <project_dir> [<project_dir> ...]
  각 프로젝트마다 <out_root>/<이름>/samples.jsonl 을 만든다 (eval_rerank.py collect 호출).
규칙:
  - 언어: 소스 파일 확장자 다수결 (.c 가 많으면 C11, 아니면 C++17). compile_flags.txt 는 프로젝트 전체에 하나뿐이라서.
  - include 경로: 프로젝트 루트, include/, src/, lib/ 와 깊이 3 이내의 모든 include 디렉터리(및 그 부모).
  - 파일: 테스트/벤치/예제/외부 코드 경로를 뺀 소스 파일을 크기순으로 최대 MAX_FILES개. 소스가 없으면(헤더 전용) 테스트·예제 파일로 대신한다.
"""
import os, subprocess, sys

MAX_FILES = int(os.environ.get("MAX_FILES", "14"))
PER_FILE = os.environ.get("EVAL_PER_FILE", "50")
SKIP = ("test", "bench", "example", "sample", "third_party", "thirdparty", "3rdparty", "extern", "external", "deps",
        "vendor", "fuzz", "contrib", "tools", "docs", "cmake", "build", ".git", "programs/legacy")
SRC_EXT = (".c", ".cc", ".cpp", ".cxx")
HERE = os.path.dirname(os.path.abspath(__file__))


def walk_sources(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in (".git", "build")]
        for fn in fns:
            if fn.endswith(SRC_EXT):
                yield os.path.relpath(os.path.join(dp, fn), root)


def pick_files(root):
    allsrc = list(walk_sources(root))
    main = [f for f in allsrc if not any(s in f.lower().split(os.sep) or f".{s}" in f.lower() for s in SKIP)]
    pool = main if len(main) >= 3 else allsrc  # 헤더 전용 라이브러리: 테스트·예제로 대신
    pool.sort(key=lambda f: -os.path.getsize(os.path.join(root, f)))
    # 너무 큰 단일 파일(합본 등)은 clangd가 느리므로 1.5MB 넘으면 뺀다
    pool = [f for f in pool if os.path.getsize(os.path.join(root, f)) < 1_500_000]
    return pool[:MAX_FILES], allsrc


def include_dirs(root):
    dirs = {".", "include", "src", "lib"}
    for dp, dns, _ in os.walk(root):
        depth = dp[len(root):].count(os.sep)
        if depth > 3:
            dns[:] = []
            continue
        dns[:] = [d for d in dns if d not in (".git", "build")]
        for d in dns:
            if d == "include":
                rel = os.path.relpath(os.path.join(dp, d), root)
                dirs.add(rel)
                dirs.add(os.path.dirname(rel) or ".")
    return sorted(d for d in dirs if os.path.isdir(os.path.join(root, d)))


def main():
    out_root, projects = sys.argv[1], sys.argv[2:]
    for root in projects:
        root = os.path.abspath(root)
        name = os.path.basename(root)
        files, allsrc = pick_files(root)
        if not files:
            print(f"== {name}: 소스 파일 없음, 건너뜀", flush=True)
            continue
        c_count = sum(f.endswith(".c") for f in allsrc)
        is_c = c_count > len(allsrc) / 2
        files = [f for f in files if f.endswith(".c") == is_c]
        flags = (["-xc", "-std=c11"] if is_c else ["-xc++", "-std=c++17"]) + [f"-I{d}" for d in include_dirs(root)]
        with open(os.path.join(root, "compile_flags.txt"), "w") as f:
            f.write("\n".join(flags) + "\n")
        print(f"== {name} ({'C' if is_c else 'C++'}, {len(files)} files, {len(flags) - 2} include dirs)", flush=True)
        env = {**os.environ, "EVAL_ROOT": root, "EVAL_FILES": ",".join(files), "EVAL_TOPDOWN": "1", "EVAL_PER_FILE": PER_FILE}
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "eval_rerank.py"), "collect", os.path.join(out_root, name)],
                           env=env, capture_output=True, text=True)
        print((r.stdout.strip().split("\n") or [""])[-1], flush=True)
        if r.returncode:
            print(r.stderr[-400:], flush=True)


if __name__ == "__main__":
    main()
