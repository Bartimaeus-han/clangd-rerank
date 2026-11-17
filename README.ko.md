# clangd Rerank

**clangd 자동완성 목록에서 내가 쓸 항목을 맨 위로 올려 주는 로컬 소형 모델.**

[English](README.md) · [설치](INSTALL.ko.md) · [연구 기록](docs/RESEARCH.md) · MIT

<!-- 데모 GIF 자리: docs/demo.gif -->

clangd 는 *무엇을* 쓸 수 있는지는 잘 알지만, 그중 *무엇을* 쓸지는 잘 못 고른다. 처음 보는 C++ 코드에서
아무것도 안 친 상태로 자동완성을 열면, 미리 선택된 항목이 정답인 경우가 28% 뿐이다.
clangd Rerank 는 clangd 의 후보를 그대로 두고 **순서만** 다시 매긴다. 이 일 하나만 하도록 파인튜닝한
0.8B 모델을 쓴다. 맨 위 항목이 정답인 비율이 79% 가 된다.

선택 기능으로 **Namer** 도 있다. 새 변수·매개변수·함수 이름을 선언하는 자리에서 이름 후보 1~3개를
평소 드롭다운 항목(`✦` 표시)으로 넣어 준다. 인라인 고스트 텍스트는 쓰지 않는다.

모든 계산은 내 GPU 에서 돈다. 코드는 밖으로 나가지 않는다.

## 결과

**2026-03-01 이후 생성된** GitHub 저장소 38개(기반 모델 공개 이후, 21개 주제: 게임·임베디드·Qt·에뮬레이터 등,
허용 라이선스만, 학습 데이터와 파일 중복 0)에서 측정했다. "1위 정답" = 미리 선택된 항목이 원래 작성자가 실제로 쓴 식별자.

**Sorter (재정렬)** — 자동완성 자리 2,087곳, 요청 5,647건

| 친 글자 | clangd 순서 | clangd Rerank |
|---|---|---|
| 없음 (`obj.`, `ns::`, 단어 시작) | 28.3% | **79.3%** |
| 1글자 | 59.6% | **90.8%** |
| 2글자 | 68.3% | **91.5%** |
| 같은 이름 변형이 있는 자리 (`std::string` / `std::pmr::string`) | 32.7% | **84.7%** |
| 전체 | 52.5% | **87.9%** |

지연: 모델 약 50ms, 프록시 끝까지 70~90ms (RTX 4080 SUPER). 400ms 안에 답이 없으면 clangd 순서를 그대로 보여 주므로 타이핑을 막지 않는다.

**Namer (선언 자리 이름)** — 357곳

| 친 글자 | 1위가 정확히 같은 이름 | 5위 안 |
|---|---|---|
| 없음 | 47.6% | 63.0% |
| 1글자 | 63.6% | 75.4% |
| 2글자 | 68.9% | 82.1% |

응답 중앙값: 새 자리 0.10초, 이어서 칠 때 0.05초 (p90 0.15초).
참고로 같은 문맥을 받은 클라우드 LLM(Claude Haiku 5.5)은 47.9 / 59.7 / 62.7% 였다.

이 수치가 **다루지 않는 것**: 정답이 clangd 후보에 있는 자리만 셌고, 코드를 위에서 아래로 쓰는 상황(커서 뒤 코드 없음)을
가정했다. 방법과 중간 결과 전부: [docs/RESEARCH.md](docs/RESEARCH.md).

## 동작 방식

```
VS Code ── clangd 확장 ── 프록시 ──────────────────────── clangd
                            │  자동완성 응답
                            ├─ 2단계: LightGBM 랭커 (순수 파이썬, 수 ms) → 상위 60개
                            ├─ 3단계: Sorter, Qwen3.5-0.8B + LoRA (로컬 서버) → 최종 순서
                            └─ 선언 자리면 → Namer, Qwen2.5-Coder-7B (llama.cpp) → ✦ 항목
```

- VS Code 확장이 `clangd.path` 를 작은 런처로 바꿔 에디터와 진짜 clangd 사이에 프록시를 끼운다.
  자동완성 응답의 `sortText` 만 바꾸고 나머지는 건드리지 않는다.
- **Sorter** 는 커서 앞 40줄을 읽고 후보에 점수를 매긴다. 공개 프로젝트 약 240개(라이브러리 24, 응용 219)와
  알고리즘 대회 풀이에서 뽑은 약 11만 건으로 학습했다. v5 부터는 이름이 같고 들어가는 글이 다른 항목도 구분해서,
  `string` 을 치면 `std::pmr::string` 이 먼저 뜨던 문제가 없어졌다.
- **Namer** 는 새 이름을 선언하는 자리(커서 앞 글로 판별)에서만 돈다. 친 글자로 시작하는 올바른 식별자만 나오도록
  디코딩을 제한하고, llama.cpp 저수준 API 위에서 이름 단위 빔 탐색을 한다.

## 요구 사항

- Linux, WSL2, 또는 원격 Linux (Remote-SSH). **Windows 로컬은 아직 지원하지 않는다.**
- NVIDIA GPU: Sorter 만 약 4GB, Sorter + Namer 약 12GB (16GB 카드 권장).
- VS Code 에서 [clangd 확장](https://marketplace.visualstudio.com/items?itemName=llvm-vs-code-extensions.vscode-clangd) 이 이미 동작할 것.

모델 서버 두 개를 직접 띄우는 셀프호스트 초기 공개판이다. **[INSTALL.ko.md](INSTALL.ko.md)** 참고.
확장은 아직 마켓플레이스에 없고, `.vsix` 는 [Releases](https://github.com/Bartimaeus-han/clangd-rerank/releases) 에 있다.

## 만든 방식

코드 작성, 실험 실행, 문서 초안에 AI 코딩 도구(Claude Code)를 많이 썼다. 문제 설정과 설계 결정(순서만 바꾼다,
인라인 대신 드롭다운, 기반 모델 공개 이후 저장소로 측정), 무엇을 채택하고 버릴지는 내가 정했고, 위 수치는 전부
이 저장소의 스크립트로 낸 것이다.

## 모델과 라이선스

- 코드: MIT.
- Sorter 기반: Qwen3.5-0.8B-Base (Apache-2.0) + 이 프로젝트의 LoRA 어댑터, [Kev](https://github.com/jaredpalmer/kev) 로 서빙.
- Namer: [Qwen2.5-Coder-7B](https://huggingface.co/Qwen/Qwen2.5-Coder-7B) (Apache-2.0), GGUF 는
  `ggml-org/Qwen2.5-Coder-7B-Q8_0-GGUF`, [llama.cpp](https://github.com/ggml-org/llama.cpp) (llama-cpp-python) 로 서빙.
