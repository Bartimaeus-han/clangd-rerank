# Namer 서빙 엔진 교체 (2026-11-13)

HF transformers + bitsandbytes NF4 → **llama.cpp (llama-cpp-python 0.3.36 cu130 저수준 API) + 새 디코딩**.
같은 HTTP 요청(`POST /v1/gen`, 파일 시작~커서 앞 + 친 글자)으로 신선 시험셋(`eval_data/eval_gen_fresh_decl`, decl 357곳 + new 142곳,
접두어 0/1/2글자 = 1,497 요청)을 `scripts/gen_http_eval.py` 로 채점. 지연은 클라이언트 왕복(같은 자리에서 0→1→2글자 순서로 보내므로
1·2글자는 프롬프트 KV 재사용이 걸린다 = 실사용과 같은 모양). RTX 4080 SUPER, WSL2, 측정 중 GPU 단독.

| 서버 | decl exact@1 0/1/2 | decl exact@5 0/1/2 | new exact@1 0/1/2 | 지연 중앙값 0/1/2글자 | p90 0글자 | 최대 | GPU 전체 사용 |
|---|---|---|---|---|---|---|---|
| 이전: HF 7B NF4 빔3 (`gen_server.py`) | 45.7 / 63.0 / 67.8 | 52.1 / 66.9 / 73.4 | 57.7 / 71.8 / 76.1 | 940 / 935 / 930 ms | 2,619 ms | 14.5 s | — |
| **llama.cpp Q8_0 (채택)** | **47.6 / 63.6 / 68.9** | **63.0 / 75.4 / 82.1** | **63.4** / 71.1 / **76.8** | **97 / 49 / 49 ms** | **147 ms** | 483 ms | 9.1 GB |
| llama.cpp Q5_K_M | 47.3 / 63.9 / 69.5 | 61.6 / 75.6 / 81.8 | 62.0 / 71.1 / 76.8 | 93 / 38 / 39 ms | 133 ms | 351 ms | 6.7 GB |

(GPU 전체 사용 = Namer 하나만 올렸을 때 nvidia-smi 값, 데스크톱 등 약 2.6 GB 포함. Sorter v5 를 같이 올리면 Q8_0 기준 11.3 GB.)

채택 기준(README "다음 할 일 2."): 정확도 1%p 넘게 하락 없음 → 통과(유일한 하락은 new 1글자 -0.7%p), 지연 0.2초 이하 → 통과(p90 기준).
이전 서버의 실제 지연은 예전에 잰 0.57초(60곳 표본)보다 훨씬 길었다: 전체 시험셋 중앙값 0.94초, p90 2.6초 → 프록시 생성 한도(0.8초)를
절반 넘게 넘겨, 실사용에서 생성 제안이 자주 버려지고 있었을 것이다.

## 바뀐 것
- 디코딩(엔진과 무관, 2026-11-13 실험 `decode_exp.py`에서 검증): 이름 단위 빔(W=3, 이름이 끝나면 P(이름)×P(경계)로 확정, 같은 이름은 합침),
  토큰 치유(프롬프트 끝 홑 공백을 떼고 첫 토큰이 ' '+식별자로 시작), 글자 단위 친-글자 제약(정렬 토큰 표 이분 탐색 마스크, LRU 512).
  요청당 forward 평균 약 3회(이전 고정 8회).
- 엔진: 프롬프트는 0번 시퀀스에 두고 요청 사이에 공통 접두를 재사용, 빔은 kv_unified 시퀀스 복사(메타데이터만).
- 모델 파일: `ggml-org/Qwen2.5-Coder-7B-Q8_0-GGUF` (sha256 0ef48dc9…4aaf, HF LFS etag 와 일치),
  비교용 `mradermacher/Qwen2.5-Coder-7B-GGUF` Q5_K_M (sha256 a4151626…c5cc). 둘 다 Apache-2.0 원본(Qwen/Qwen2.5-Coder-7B)의 변환본.
  토큰화는 HF 토크나이저와 시험셋 프롬프트 499개 전부 동일(BOS 없음).
- 직접 변환(`convert_hf_to_gguf.py`)은 자동 권한 검사에서 막혀(내려받은 저장소 코드 실행) 하지 않았다.

## 재현
```
~/projects/clangd-rerank/scripts/run_namer_llama.sh [<gguf>] --port 8010      # 서버
python3 -I scripts/gen_http_eval.py eval_data/eval_gen_fresh_decl --tag <이름> --url http://127.0.0.1:8010
python3 -I scripts/gen_report.py eval_data/eval_gen_fresh_decl/samples.jsonl eval_data/eval_gen_fresh_decl/<이름>-gen.jsonl
```
환경: `~/work/clangd-rerank/ext/llama-venv` (python 3.12, llama-cpp-python 0.3.36 cu130 휠 sha256 4e81d9f3…cd15e,
nvidia-cuda-runtime 13.0, nvidia-cublas 13), 모델 `~/work/clangd-rerank/ext/gguf/`.

## 남은 것
- 새 자리 첫 요청(콜드 prefill)은 수백 토큰 프롬프트에서 100~270 ms. 커서가 선언 자리에 오기 전에 미리 계산(pre-warm)하면 더 줄일 수 있다.
- 배포: llama-cpp-python CUDA 휠이 크다(Linux 782 MB + CUDA 런타임). Windows 런처·설치 스크립트 과제와 함께 정리.
- INSTALL.md 는 아직 HF 경로 기준.
