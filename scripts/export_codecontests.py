"""deepmind/code_contests 의 C++ 풀이를 독립 .cpp 파일로 내보낸다 (std 중심 코드 다양화용; 학습 소스 'codecontests').
사용: export_codecontests.py <out_dir> [문제 수=600] [문제당 풀이 수=2]
문제당 길이 중앙값에 가까운 풀이부터 고른다 (너무 짧거나 긴 것 제외). compile_flags.txt 도 만든다.
"""
import itertools, os, sys
from datasets import load_dataset

out, n_prob, per = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 600, int(sys.argv[3]) if len(sys.argv) > 3 else 2
os.makedirs(out, exist_ok=True)
open(os.path.join(out, "compile_flags.txt"), "w").write("-xc++\n-std=c++17\n")
ds = load_dataset("deepmind/code_contests", split="train", streaming=True)
written = 0
for i, ex in enumerate(itertools.islice(ds, n_prob)):
    sol = ex["solutions"]
    cpp = [c for lang, c in zip(sol["language"], sol["solution"]) if lang == 2 and 400 <= len(c) <= 6000]
    if not cpp:
        continue
    cpp.sort(key=len)
    mid = len(cpp) // 2
    picks = cpp[max(0, mid - per // 2): max(0, mid - per // 2) + per]
    for j, code in enumerate(picks):
        with open(os.path.join(out, f"p{i:04d}_{j}.cpp"), "w") as f:
            f.write(code if code.endswith("\n") else code + "\n")
        written += 1
    if (i + 1) % 100 == 0:
        print(f"  {i + 1} 문제, {written} 파일", flush=True)
print(f"완료: {written} 파일 -> {out}")
