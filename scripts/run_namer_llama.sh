#!/usr/bin/env bash
# llama.cpp 판 Namer 서버 실행 (gen_server_llama.py). CUDA 런타임은 venv 안의 nvidia pip 패키지에서 찾는다.
# 사용: run_namer_llama.sh [<모델.gguf>] [추가 인자...]
#   기본 모델: <저장소>/ext/gguf/qwen2.5-coder-7b-q8_0.gguf (ggml-org/Qwen2.5-Coder-7B-Q8_0-GGUF),
#   없으면 ~/work/clangd-rerank/ext/gguf/ 의 같은 파일.
#   환경 변수 LLAMA_VENV 로 venv 를 바꿀 수 있다 (기본 <저장소>/ext/llama-venv, 없으면 ~/work/clangd-rerank/ext/llama-venv:
#   llama-cpp-python 0.3.36 cu130 휠 + nvidia-cuda-runtime 13.0 + nvidia-cublas 13; INSTALL.md 4절).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
pick() { if [ -e "$REPO/$1" ]; then echo "$REPO/$1"; else echo "$HOME/work/clangd-rerank/$1"; fi; }
V=${LLAMA_VENV:-$(pick ext/llama-venv)}
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then GGUF=$1; shift; else GGUF=$(pick ext/gguf/qwen2.5-coder-7b-q8_0.gguf); fi
CU=$(ls -d "$V"/lib/python3*/site-packages/nvidia/cu13/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="${CU}:/usr/lib/wsl/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$V/bin/python" "$HERE/gen_server_llama.py" --gguf "$GGUF" "$@"
