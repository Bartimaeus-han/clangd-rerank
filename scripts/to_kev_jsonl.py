"""clangd 샘플(samples.jsonl)을 Kev 학습 형식(JSONL, 질문마다 label)으로 바꾼다.

사용: to_kev_jsonl.py <출력.jsonl> <samples.jsonl> [<samples.jsonl> ...]
지시문과 후보 설명은 평가 때(v1)와 똑같이 맞춘다.
Kev 학습기의 길이 한도에 맞춰 문맥은 커서 앞 CTX_LINES줄, 후보는 clangd 상위 MAX_CANDS개로 자른다.
정답이 상위 MAX_CANDS개 밖에 있는 항목은 Kev가 고를 수 없으므로 빼고, 그 수를 따로 출력한다.
"""
import json, os, sys

INSTRUCTIONS = "C++ code with a <CURSOR> marker. Which identifier will the programmer most likely type at <CURSOR>?"
CTX_LINES = int(os.environ.get("CTX_LINES", "40"))
MAX_CANDS = int(os.environ.get("MAX_CANDS", "60"))
OVERSAMPLE_KIND = os.environ.get("OVERSAMPLE_KIND", "")      # 예: scope — 이 종류의 위치를 OVERSAMPLE_N 배로 복제
OVERSAMPLE_N = int(os.environ.get("OVERSAMPLE_N", "1"))


def main():
    out_path, inputs = sys.argv[1], sys.argv[2:]
    n = dropped = 0
    with open(out_path, "w") as out:
        for path in inputs:
            for line in open(path):
                s = json.loads(line)
                reps = OVERSAMPLE_N if OVERSAMPLE_KIND and s.get("kind") == OVERSAMPLE_KIND else 1
                for lv in list(s["levels"].values()) * reps:
                    cands = lv["cands"][:MAX_CANDS]
                    if s["gold"] not in [c["name"] for c in cands]:
                        dropped += 1
                        continue
                    before, cursor = lv["state"].split("<CURSOR>")[0].rsplit("\n", 1) if "\n" in lv["state"].split("<CURSOR>")[0] else ("", lv["state"].split("<CURSOR>")[0])
                    state = "\n".join(before.split("\n")[-(CTX_LINES - 1):] + [cursor + "<CURSOR>"])
                    out.write(json.dumps({
                        "state": state,
                        "questions": {"next": {
                            "type": "choice",
                            "instructions": INSTRUCTIONS,
                            "criteria": {c["name"]: c["detail"] for c in cands},
                            "label": s["gold"],
                        }},
                    }) + "\n")
                    n += 1
    print(f"{out_path}: {n}건 (정답이 상위 {MAX_CANDS}개 밖이라 제외 {dropped}건, {100 * dropped / max(1, n + dropped):.1f}%)")


if __name__ == "__main__":
    main()
