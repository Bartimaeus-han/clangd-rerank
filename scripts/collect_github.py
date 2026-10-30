"""GitHub에서 '보통 개발자가 쓴' C++ 애플리케이션 저장소를 주제별로 찾아 얕게 clone 한다 (학습 데이터 다양화용).

사용: collect_github.py <clone_root> <topic> [<topic> ...]
환경: PER_TOPIC(기본 15), STARS(기본 5..500), MAX_SIZE_KB(기본 150000), PUSHED(기본 >2022-01-01), SORT(기본 updated),
      CREATED(예: ">2026-03-01" — 기반 모델 공개 이후 생긴 저장소만, 신선 시험셋용), EXCLUDE_MANIFESTS(쉼표 구분, 거기 있는 저장소는 제외)
규칙:
  - 라이선스는 허용적인 것만 (MIT, Apache-2.0, BSD-2/3, ISC, Zlib, Unlicense, CC0, BSL-1.0). GPL/LGPL/MPL/없음 은 뺀다.
  - fork·archived 제외, 이름/설명에 library·header-only·framework·sdk 가 있으면 제외 (라이브러리가 아니라 응용 코드가 목적).
  - 이미 학습·시험에 쓴 프로젝트 이름은 제외.
  - 검색 API 는 분당 30회라 호출 사이에 2.2초 쉰다. clone 은 --depth 1, 120초 제한.
  - <clone_root>/manifest.jsonl 에 저장소 정보(이름, 라이선스, 별, 크기, 주제, 경로)를 한 줄씩 덧붙인다.
clone 한 폴더는 외부 코드이므로 빌드하지 말고 collect_auto.py(clangd 만 실행)로만 읽는다.
"""
import json, os, re, subprocess, sys, time

PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "Unlicense", "CC0-1.0", "BSL-1.0", "0BSD"}
USED = {"lua", "zstd", "tinyxml2", "abseil-cpp", "spdlog", "json", "glm", "CLI11", "cJSON", "lz4", "zlib", "mbedtls", "stb", "Catch2",
        "doctest", "cxxopts", "entt", "magic_enum", "range-v3", "toml11", "yaml-cpp", "cereal", "simdjson", "box2d", "raylib",
        "googletest", "benchmark", "libuv", "foundationdb", "fmt"}
LIBRARY_WORDS = re.compile(r"\b(library|header[- ]only|framework|sdk|wrapper|bindings?)\b", re.I)
PER_TOPIC = int(os.environ.get("PER_TOPIC", "15"))
STARS = os.environ.get("STARS", "5..500")
MAX_SIZE_KB = int(os.environ.get("MAX_SIZE_KB", "150000"))
PUSHED = os.environ.get("PUSHED", ">2022-01-01")
SORT = os.environ.get("SORT", "updated")
CREATED = os.environ.get("CREATED", "")
EXCLUDE_MANIFESTS = [m for m in os.environ.get("EXCLUDE_MANIFESTS", "").split(",") if m]


def search(topic, page):
    q = f"language:C++ topic:{topic} stars:{STARS} size:<{MAX_SIZE_KB} pushed:{PUSHED} archived:false fork:false"
    if CREATED:
        q += f" created:{CREATED}"
    r = subprocess.run(["gh", "api", "-X", "GET", "search/repositories", "-f", f"q={q}", "-f", "per_page=50",
                        "-f", f"page={page}", "-f", f"sort={SORT}"], capture_output=True, text=True)
    time.sleep(2.2)
    if r.returncode:
        print(f"   검색 실패 ({topic} p{page}): {r.stderr.strip()[:160]}", flush=True)
        return []
    return json.loads(r.stdout).get("items", [])


def ok(item, seen):
    lic = (item.get("license") or {}).get("spdx_id")
    name = item["name"]
    text = f"{name} {item.get('description') or ''}"
    if lic not in PERMISSIVE or item["full_name"] in seen or name in USED:
        return False
    if LIBRARY_WORDS.search(text):
        return False
    return True


def main():
    root = os.path.abspath(sys.argv[1])
    topics = sys.argv[2:]
    os.makedirs(root, exist_ok=True)
    manifest = os.path.join(root, "manifest.jsonl")
    seen = set()
    if os.path.exists(manifest):
        seen = {json.loads(l)["full_name"] for l in open(manifest)}
    for mp in EXCLUDE_MANIFESTS:  # 이전 학습·시험 수집에 들어간 저장소는 다시 받지 않는다
        if os.path.exists(mp):
            seen |= {json.loads(l)["full_name"] for l in open(mp)}
    if EXCLUDE_MANIFESTS:
        print(f"제외 목록 {len(seen)}개 (이전 수집)", flush=True)
    for topic in topics:
        got, page = 0, 1
        while got < PER_TOPIC and page <= 4:
            items = search(topic, page)
            page += 1
            if not items:
                break
            for it in items:
                if got >= PER_TOPIC or not ok(it, seen):
                    continue
                dest = os.path.join(root, f"{topic}__{it['owner']['login']}__{it['name']}")
                if not os.path.isdir(dest):
                    r = subprocess.run(["git", "clone", "--depth", "1", "--single-branch", "--quiet", "--config", "core.hooksPath=/dev/null",
                                        it["clone_url"], dest], capture_output=True, text=True, timeout=120)
                    if r.returncode:
                        print(f"   clone 실패 {it['full_name']}: {r.stderr.strip()[:120]}", flush=True)
                        continue
                seen.add(it["full_name"])
                got += 1
                with open(manifest, "a") as f:
                    f.write(json.dumps({"full_name": it["full_name"], "license": it["license"]["spdx_id"], "stars": it["stargazers_count"],
                                        "size_kb": it["size"], "topics": it.get("topics", []), "topic": topic, "path": dest,
                                        "pushed_at": it["pushed_at"]}) + "\n")
                print(f"   + {it['full_name']} ★{it['stargazers_count']} {it['license']['spdx_id']} {it['size'] // 1024}MB", flush=True)
        print(f"== {topic}: {got}개", flush=True)


if __name__ == "__main__":
    main()
