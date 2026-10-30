#!/usr/bin/env bash
# 학습용 공개 프로젝트에서 clangd 후보 샘플을 모은다. 결과: train_out/<프로젝트>/samples.jsonl
# 평가용(fmt, Bartimaeus_app)은 여기 넣지 않는다.
set -uo pipefail
S="$(cd "$(dirname "$0")/.." && pwd)"
T="$S/train_src"
PY="$S/jevenv/bin/python -I $S/clangd_test/eval_rerank.py collect"
mkdir -p "$S/train_out"

run() {  # run <이름> <루트> <파일당 상한> <파일...>
  local name=$1 root=$2 per=$3; shift 3
  local files; files=$(IFS=,; echo "$*")
  echo "== $name ($# files)"
  EVAL_ROOT="$root" EVAL_TOPDOWN=1 EVAL_PER_FILE=$per EVAL_FILES="$files" $PY "$S/train_out/$name" 2>&1 | tail -1
}

cd "$T/lua" && printf '%s\n' -xc -std=c99 -I. > compile_flags.txt
run lua "$T/lua" 50 lapi.c lauxlib.c lbaselib.c lcode.c ldebug.c ldo.c lgc.c llex.c lobject.c lparser.c lstrlib.c ltable.c lvm.c

cd "$T/zstd" && printf '%s\n' -xc -std=c99 -Ilib -Ilib/common -Ilib/compress -Ilib/decompress > compile_flags.txt
run zstd "$T/zstd" 50 lib/compress/zstd_compress.c lib/compress/zstd_lazy.c lib/compress/huf_compress.c lib/compress/fse_compress.c lib/decompress/zstd_decompress.c lib/decompress/zstd_decompress_block.c lib/common/entropy_common.c programs/fileio.c programs/zstdcli.c programs/benchzstd.c

cd "$T/tinyxml2" && printf '%s\n' -xc++ -std=c++17 -I. > compile_flags.txt
run tinyxml2 "$T/tinyxml2" 120 tinyxml2.cpp xmltest.cpp

cd "$T/abseil-cpp" && printf '%s\n' -xc++ -std=c++17 -I. > compile_flags.txt
run abseil "$T/abseil-cpp" 50 absl/strings/ascii.cc absl/strings/charconv.cc absl/strings/cord.cc absl/strings/escaping.cc absl/strings/numbers.cc absl/strings/str_cat.cc absl/strings/str_replace.cc absl/strings/str_split.cc absl/time/time.cc absl/time/duration.cc absl/container/internal/raw_hash_set.cc absl/synchronization/mutex.cc

cd "$T/spdlog" && printf '%s\n' -xc++ -std=c++17 -Iinclude -DSPDLOG_COMPILED_LIB > compile_flags.txt
run spdlog "$T/spdlog" 50 src/async.cpp src/cfg.cpp src/file_sinks.cpp src/spdlog.cpp src/stdout_sinks.cpp $(cd "$T/spdlog" && ls tests/test_*.cpp | head -8)

cd "$T/json" && printf '%s\n' -xc++ -std=c++17 -Iinclude -Itests/thirdparty/doctest -Itests/src > compile_flags.txt
run json "$T/json" 40 $(cd "$T/json" && ls tests/src/unit-*.cpp | head -14)

cd "$T/CLI11" && printf '%s\n' -xc++ -std=c++17 -Iinclude > compile_flags.txt
run CLI11 "$T/CLI11" 40 $(cd "$T/CLI11" && ls examples/*.cpp | head -14)

cd "$T/glm" && printf '%s\n' -xc++ -std=c++17 -I. > compile_flags.txt
run glm "$T/glm" 40 $(cd "$T/glm" && ls test/core/core_func_*.cpp test/gtc/*.cpp 2>/dev/null | head -14)
