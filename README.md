# clangd 자동완성 재정렬 연구 — 보존본 (1차 2026-10-26, 2차 2026-10-27, 3·4·5차 2026-10-27~28)

clangd가 만든 자동완성 후보의 순서를 결정 모델(Jev, Kev)로 다시 매기는 실험의 결과물.
조사 문서(배경·선행 연구·결과): https://claude.ai/artifact/PwnEfkhiMjvhugkdv1ofsu

## 구조 (합의된 3단계)

1. clangd — 후보 생성 (최대 255개)
2. 2단계 특징 랭커 — LightGBM lambdarank (`scripts/stage1_ranker.py`, 모델 `models/stage2-lgb/stage2_v2_lgb.txt`).
   clangd 순위, 종류, 이름 길이, 문맥 등장 횟수/마지막 등장 줄 수, 서브토큰 겹침 등으로 상위 K개(기본 60)를 고른다. 2~3ms.
3. 3단계 Kev-0.8B 파인튜닝 모델 — 상위 K개를 Choice 질문으로 채점해 순서를 정한다. 서빙 왕복 중앙값 50ms.

LSP 프록시 `scripts/clangd_rerank_proxy.py` 가 1→2→3을 묶는다 (VS Code `clangd.path`를 이 파일로). 2단계 평가는 `stage2_lite.py`(표준 라이브러리만, lightgbm과 결과 동일, 255개 후보 11ms)로 하므로 프록시는 python3만 있으면 돈다.

`vscode-extension/` — VS Code 확장 v0.1 소스(2026-10-27 시작). `clangd.path`를 런처로 바꿔 프록시를 끼우고, 백엔드(local/jev/stage2Only)를 설정으로 고른다. 빌드·설치 방법은 그 안의 README.

## 폴더

- `models/kev-0.8b-clangd-v4/` — **최종 모델**(2026-10-28, 4차). Kev-0.8B(Qwen3.5-0.8B-Base) LoRA 어댑터 + pointer head.
  학습: 243 소스 99,308건(`train_v4_sources.txt` = v2 24 라이브러리 + 응용 219 프로젝트 + codecontests 1,000; 3,021건은 문맥 초과로 제외), 레시피는 v2와 동일, 5h19m(12,036 스텝). 로그 `results/train_v4.log`.
  실행은 v2와 같다(`--run <이 폴더>`). 결과 `results/compare-v4.txt`, `compare-v4-app.txt`, 세 모델 비교 `summary_v2e1_v3s3_v4.md`.
- `models/kev-0.8b-clangd-v2/` — 2차 모델(v4 이전 최종, 비교 기준). 같은 구조.
  학습: 24개 공개 프로젝트 37,080건(`train_v2_sources.txt`), 1 epoch, lr 5e-5, batch 1 × accum 8, bf16,
  --max_state 1400, 증강 끔(--p_none 0 --p_none_distract 0 --p_distract 0), 121분. 로그 `train.log`.
  실행: `python -m kev.serve --run <이 폴더> --port 8009 --host 127.0.0.1` (jaredpalmer/kev 저장소 커밋 2074cc4의 venv에서;
  `KEV_CUDA_GRAPHS=0 KEV_PREFIX_CACHE=0` 권장). 첫 요청은 커널 컴파일로 10초 넘게 걸리므로 워밍업 필요.
- `models/kev-0.8b-clangd-v1/` — 1차 모델(7개 프로젝트 8,450건, 2 epoch, lr 2e-5). 비교용.
- `models/stage2-lgb/` — 2단계 LightGBM 모델 v1(7개 프로젝트), v2(24개 소스, 110트리; 최종).
- `scripts/` — 수집(`eval_rerank.py collect`, `collect_auto.py`, `collect_train.sh`), 변환(`to_kev_jsonl.py`),
  Jev 재정렬(`eval_rerank.py jev`, `run_jev.sh`), 로컬 평가(`kev_local_eval.py`, `eval_ckpt.sh`), 비교(`compare_models.py`),
  2단계(`stage1_ranker.py` 학습, `stage2_reorder.py` 세트 생성, `eval_s2.sh` + `stage_f_report.py` 전체 기준 보고),
  하이퍼파라미터 탐색(`sweep.py`), 서빙 측정(`serve_bench.py`, `serve_kev.sh`), 프록시(`clangd_rerank_proxy.py`, `proxy_smoke.py`, 실사용 집계 `rerank_stats.py`, 시험 `test_sites.py`),
  데이터 다양화(`collect_github.py` GitHub 주제별 수집, `export_codecontests.py`, `build_v4.py` 편향 규칙 선별), v4 학습(`train_v4.sh`, 학습 종료 대기 후 평가 `run_after_train_v4.sh`), 통합 평가(`eval_full.sh` = 라이브러리 5세트 + 응용, 모델 간 비교표 `summarize_compare.py`),
  작업 폴더 복구(`restore_scratchpad.sh <scratchpad>`: 디스크 `~/work/clangd-rerank/`의 ext/kev·kev_data·eval_*·train_* 을 심볼릭 링크로 되살림).
  `run_jev.sh`는 같은 폴더의 `jev.env`(TYPESAFE_API_KEY)와 `jevenv/`를 기대한다 — 키 파일은 여기 넣지 않았다.
- `eval_data/` — Kev 형식 JSONL: `train.jsonl`(1차), `train_v2.jsonl`(2차 38,674건), `val.jsonl`(CLI11), `test_{fmt,lz4,entt,cxxopts}.jsonl`;
  clangd 샘플+Jev 결과 `eval_{cli,fmt,lz4,entt,cxxopts}60/`; 2단계로 거른 세트 `stage2_sets/s2k{60,30}_<proj>.jsonl`;
  응용 코드 시험셋 `test_app_sub.jsonl`(5,911건), `eval_app_sub/samples.jsonl`(2,070곳), `eval_app60_sub/`(상위60 컷 1,873곳 + Jev 결과).
  큰 원본(수집 소스 7GB, 추출 샘플, `train_v4.jsonl` 422MB, Kev venv)은 디스크 `~/work/clangd-rerank/`에 있다(train_src2, train_out3, train_out3_sel, kev_data, ext/kev).
- `results/` — `results.tsv`(탐색), `compare-v2e1.txt`/`compare-v2e2.txt`(모델별 비교표), `stage_f-v2e1.txt`(전체 기준),
  `serve_bench-v2e1.txt`(서빙 지연), `proxy_v2.log`, `train_v2_e2.log`, `compare-v2e1-app.txt`/`compare-v3s3-app.txt`(응용 시험셋),
  `compare-v3s3.txt`(scope 가중 모델), `composition.txt`·`v4_summary.txt`·`app_test_pick.json`(v4 데이터 구성), `OVERNIGHT_PLAN.md`(시간순 작업 기록),
  `compare-v4.txt`/`compare-v4-app.txt`/`pred-v4-test_app_sub.jsonl`/`train_v4.log`(4차 최종 모델), `summary_v2e1_v3s3_v4.md`(v2-e1·v3·v4 비교표, `summarize_compare.py` 출력).
- `vscode-extension/` — VS Code 확장 v0.1 소스와 `clangd-rerank-0.1.0.vsix`(아래 3차 진행 참고). `train_v4_sources.txt` — v4 학습 소스 243개.

## 2차 결과 (문맥 40줄, clangd 상위 60개, 미리 선택 항목 정답률 R@1)

0글자(빈 접두어):

| 데이터 | 위치 | clangd | 1차 모델 | 2차 모델 | Jev |
|---|---|---|---|---|---|
| CLI11 (검증) | 266 | 18.0% | 53.8% | **67.3%** | 69.9% |
| fmt (시험) | 428 | 19.6% | 68.5%¹ | **83.2%** | 62.4% |
| lz4 (시험) | 389² | 17.5% | – | **68.4%** | 60.9% |
| entt (시험) | 59 | 25.4% | – | **93.2%** | 74.6% |
| cxxopts (시험) | 143 | 18.2% | – | **77.6%** | 73.4% |

¹ 1차 학습셋의 spdlog가 fmt를 번들해 유리했을 수 있음. 2차 학습셋은 spdlog를 뺐다.
² fp32 평가 경로의 1,400 토큰 한도를 넘는 긴 줄 위치 제외. 서빙 경로 한도는 65,536 토큰이라 실제 배포엔 영향 없음.

1글자 / 2글자: CLI11 88.0/91.4 (Jev 87.6/91.4), fmt 94.1/94.6 (83.6/93.0), lz4 86.4/89.9 (83.7/81.3),
entt 98.3/98.3 (100/100), cxxopts 88.1/89.5 (87.4/88.8). 약점은 `::` 뒤(scope): CLI11 60.3 vs Jev 86.2, cxxopts 64.1 vs 82.1.

전체 위치 기준 0글자 정답률(후보에 정답이 없는 위치를 오답으로 셈), clangd → 2단계만 → 2단계K60+2차 모델:
CLI11 15.0→31.7→62.1, fmt 15.3→31.8→78.0, lz4 14.9→21.0→53.1(K30 60.3), entt 22.1→57.4→86.8, cxxopts 16.7→31.4→75.0.
K=30과 K=60은 정확도·지연 모두 거의 같다. "2글자부터 3단계 생략" 규칙은 2차 모델에선 8~9%p 손해라 폐기(프록시 기본 RERANK_SKIP3_TYPED=0).

탐색(7개 프로젝트, 1 epoch, CLI11 0글자): lr 5e-5 65.4% ≫ head lr 2e-4 61.7% > 후보30 49.8% > 평활 48.1% > lr 2e-5 46.2%
> 문맥20 44.4% > 문맥80 42.6% > lr 1e-5 38.0% > 후보100 33.1%. 2 epoch째(lr 3e-5)는 5개 세트 중 4개에서 1~3%p 하락 → 1 epoch 모델이 최종.

서빙(bf16, RTX 4080 SUPER): 왕복 중앙값 50ms, p90 55~63ms, 후보 30/60 차이 1ms. 프록시 끝까지 72~93ms(쉬다 첫 요청 ~200ms). Jev 왕복 ~175ms.
주의: 평가에 쓴 공개 프로젝트는 베이스 모델 사전학습에 들어 있을 수 있다(공개 코드 평가의 공통 한계).

## 3차 진행 (2026-10-27 오후): 응용 코드 시험셋, scope 가중, 확장 v0.1

**학습 데이터 다양화**(사용자 요청 "일반 개발자 코드", 데이터 편향 주의): GitHub 24주제(게임·GUI·임베디드·과제·에뮬레이터 등) 252 저장소(허용 라이선스만, 별 5~500, 2022년 이후 갱신, 라이브러리·SDK 제외)
+ code_contests C++ 풀이 917 파일 수집 → 249 프로젝트 116,331 위치(member 11.1%, scope 11.4%). 주제별 1개 저장소 23개는 학습에서 완전히 빼 **응용 코드 시험셋**으로 삼았다
(eval_app_sub 2,070곳, Jev 교집합 1,858곳). 구성표 `results/composition.txt`, `results/v4_summary.txt`.

응용 코드 시험셋 R@1 (1,858곳, 상위 60개, 문맥 40줄):

| 접두어 | clangd | 2차 모델 v2-e1 | v3 (scope×3) | Jev |
|---|---|---|---|---|
| 0글자 | 29.2% | **77.3%** | 76.3% | 67.4% |
| 1글자 | 65.1% | **91.2%** | 91.1% | 86.4% |
| 2글자 | 79.3% | **94.4%** | 94.2% | 88.6% |

위치 종류별 0글자(clangd / v2-e1 / Jev): member 33.1/70.2/74.2, scope 23.8/75.1/71.9, ident 29.4/78.3/66.2. 2단계 v2 recall@60 0글자 91.0→98.7%.
**라이브러리로만 배운 모델이 응용 코드에도 그대로 일반화**한다(라이브러리 시험셋과 같은 수준, Jev보다 높음). CLI11에서 낮았던 `::`는 그 프로젝트 관습(`CLI::` 뒤 App) 탓이 컸다.

**v3 = scope 위치 3배 복제**(train_v2_scope3.jsonl 47,576건, 그 외 v2 레시피 동일, 2h59m): 라이브러리 0글자 CLI11 67.3→72.2, fmt 83.2→82.2, lz4 68.4→66.3, entt 93.2→94.9,
cxxopts 77.6→75.5(scope 64.1 그대로); n가중 합계 1,285곳 75.3→75.2, 응용 77.3→76.3 → **채택 안 함**(`results/compare-v3s3*.txt`). scope만 1~5%p 오르고 나머지가 그만큼 내린다.

**v4(데이터 준비)**: `train_v4_sources.txt` 243 소스 = v2 24 라이브러리 + 응용 219 프로젝트(프로젝트당 상한 100, 시험 라이브러리 번들 파일 300·내용 중복 파일 650 제외)
+ codecontests 1,000 → `~/work/clangd-rerank/kev_data/train_v4.jsonl` 99,308건(member 10.1%, scope 11.0%). 레시피 v2 동일. 16:28 시작 → 12분 뒤 사용자 요청으로 중단(LoRA 실행은 중간 체크포인트 없음) → 4차(아래)에서 완주.
목적은 "응용 코드 보정"이 아니라 "분포 폭 넓히기 + 추가 상승".

**VS Code 확장 v0.1**(`vscode-extension/`, 자세한 것은 그 안의 README): `clangd.path`를 런처로 바꿔 프록시를 끼우는 방식, 백엔드 local(Kev 서버) / jev(키는 SecretStorage) / stage2Only.
Node v24.22.1 LTS(`~/.local/node`)로 컴파일·패키징(`clangd-rerank-0.1.0.vsix`)해 원격(WSL) VS Code 서버에 설치했다(`code-server --install-extension`).
프록시→2단계→로컬 Kev 서버 스모크 통과(`std::vector v; v.` 뒤에서 clangd 1위 assign → 재정렬 1위 push_back; 첫 요청 1초는 커널 컴파일).
실사용 측정 기능 포함: `clangdRerank.recordStats`를 켜면 자동완성 자리마다 사용자가 결국 쓴 식별자와 그 항목의 순위(clangd/2단계/최종)를 기록, "Show usage statistics" 명령이 R@1을 보여 준다.
**아직 안 한 것**: VS Code 창을 다시 불러와 실제 타이핑 체감, 측정 수치 수집.

## 4차 진행 (2026-10-28 새벽): v4 학습·평가 → 최종 모델 채택

GPU가 비어 00:35에 `train_v4.sh` 재시작(96,287건 → 12,036 스텝, 0.197 s/rec) → 05:54 저장, 05:55~06:08 `eval_full.sh`(fp32 평가 경로, Jev 교집합 기준). **v4를 최종 모델로 채택**: 라이브러리 5세트 0글자 n가중 75.3→77.4%, 응용 77.3→79.2%, 1·2글자도 전부 v2-e1 이상.

0글자 R@1(clangd / v2-e1 / v3 / **v4** / Jev):

| 시험셋 | n | clangd | v2-e1 | v3 | **v4** | Jev |
|---|---|---|---|---|---|---|
| CLI11(검증) | 266 | 18.0 | 67.3 | 72.2 | **73.7** | 69.9 |
| fmt | 428 | 19.6 | 83.2 | 82.2 | **83.6** | 62.4 |
| lz4 | 389 | 17.5 | 68.4 | 66.3 | **69.2** | 60.9 |
| entt | 59 | 25.4 | 93.2 | 94.9 | 91.5 | 74.6 |
| cxxopts | 143 | 18.2 | 77.6 | 75.5 | **82.5** | 73.4 |
| 라이브러리 5세트 n가중 | 1,285 | - | 75.3 | 75.2 | **77.4** | - |
| 응용(23 저장소) | 1,858 | 29.2 | 77.3 | 76.3 | **79.2** | 67.4 |
| 신선(2026-03 이후 생성 38 저장소, 5차) | 1,620 | 27.0 | 75.1 | - | **76.8** | 68.6 |

응용 1글자 91.2→91.6, 2글자 94.4→95.1. 위치 종류별 0글자(v2-e1→v4): 응용 member 70.2→76.2, scope 75.1→74.6, ident 78.3→80.1;
CLI11 scope 60.3→63.8, ident 68.4→79.1, member 72.0→68.0; cxxopts scope 64.1→74.4. entt(-1.7%p)는 59곳이라 1곳 차이.
v3(scope 3배 복제)와 달리 자연 분포(scope 11%)로 데이터만 2.6배 늘린 것이 전 항목에서 고르게 올랐다 → 가중 복제보다 분포 폭이 효과적. 전체 표는 `results/summary_v2e1_v3s3_v4.md`.
지연은 같은 구조라 v2와 동일(fp32 평가 경로 중앙값 65~87ms). 평가 직후 v4 서버(8009)를 띄우고 확장 런처 경유 스모크(`smoke/t.cpp` `v.`) 통과: 1위 reserve, 2위 push_back, 2단계 2ms + 3단계 29후보 61ms. 단 서버 기동 직후 첫 요청들은 커널 워밍업으로 0.4초 시간 초과가 나 2단계 순서로 대체된다(`serve_kev.sh`에 워밍업 요청 추가).
같이 고친 것: `serve_kev.sh`가 scratchpad 기준 상대 경로(`ext/kev/runs/...`)를 못 받던 버그 수정, `summarize_compare.py`(모델 간 비교표), `run_after_train_v4.sh`(학습 종료 대기 → 평가).

### 5차 (2026-10-28 오후): 신선 시험셋 — 기반 모델 공개 이후 생긴 저장소로 재측정

사용자 질문("시험 프로젝트를 기반 모델이 사전학습 때 봤을 수 있지 않나")에 답하려고, 기반 모델 Qwen3.5-0.8B-Base 공개(2026-02 말) 이후인 **2026-03-01 이후 생성된** GitHub 저장소만 모아 다시 쟀다.
`collect_github.py`에 CREATED(`created:>2026-03-01`)·EXCLUDE_MANIFESTS(이전 수집 252개 제외) 옵션 추가, 같은 21주제 × 2개, 별 2~500, 허용 라이선스만 → 41개 clone(`results/fresh_manifest.jsonl`) → `collect_auto.py` 39 프로젝트 17,174위치
→ `build_fresh.py`(시험 라이브러리 번들 파일 0, 학습 소스와 파일 내용 중복 0, 주제당 90) → 1,808위치(member 12.2%, scope 11.3%; `results/fresh_summary.txt`) → Jev 교집합 1,620곳. 파이프라인 `scripts/run_fresh.sh`(clone 뒤 19분). 데이터 `eval_data/eval_fresh*`, `test_fresh.jsonl`.

R@1 % — 신선 1,620곳 (괄호: 응용 1,858곳):

| 접두어 | clangd | v2-e1 | **v4** | Jev |
|---|---|---|---|---|
| 0글자 | 27.0 (29.2) | 75.1 (77.3) | **76.8** (79.2) | 68.6 (67.4) |
| 1글자 | 64.1 (65.1) | 90.8 (91.2) | **91.4** (91.6) | 83.7 (86.4) |
| 2글자 | 78.4 (79.3) | 92.9 (94.4) | **93.9** (95.1) | 88.5 (88.6) |

위치 종류별 0글자(clangd / v2-e1 / v4 / Jev): member 32.2 / 68.3 / 70.7 / 73.2, scope 37.9 / 80.2 / 81.9 / 83.5, ident 24.5 / 75.5 / 77.0 / 65.7 (`results/compare-v4-fresh.txt`, `compare-v2e1-fresh.txt`).
**결론**: 기반 모델이 볼 수 없었던 코드에서 v4 0글자 79.2→76.8(-2.4%p). clangd 기본도 29.2→27.0(-2.2%p)으로 같이 내려 시험셋 자체가 조금 더 어려운 쪽이고, Jev는 오히려 +1.2%p. 사전학습 노출로 부풀려진 몫은 많아야 1~2%p이며 v4 > v2-e1(+1.7%p) > Jev 순서도 그대로다. 지연 동일(fp32 평가 경로 중앙값 73ms). Jev 비용 약 $0.38(9.0M 토큰, 누적 약 $3.6).
주의: 생성일 조건은 "저장소가 새로 만들어졌다"는 뜻이지 코드가 새로 쓰였다는 보장은 아니다(옛 코드 재업로드, AI 생성 코드 가능). 학습 소스와의 파일 해시 중복은 0이었다.

### 재개 방법

1. `tmux new -As claude` 안에서 `cd ~/projects/clangd-rerank && claude`(2026-10-30 `~/projects/study_claude/clangd-rerank`에서 이 위치로 이사). 이사 전 대화는 `cd ~/projects/study_claude && claude --resume 9089f54d-d9d0-4cc5-bee8-274e98bb2bcd`로 열린다. scratchpad(`/tmp/claude-1000/.../9089f54d-.../scratchpad`)가 비워졌으면
   `scripts/restore_scratchpad.sh <scratchpad>`로 디스크 폴더를 링크해 되살린다(Jev 키는 `jev.env`에 다시 넣는다).
2. 로컬 모델 서버: scratchpad에서 `./serve_kev.sh ext/kev/runs/clangd-0.8b-v4 8009`(= `models/kev-0.8b-clangd-v4`; setsid 로 띄우면 세션과 무관하게 남는다, 로그 `kev_data/serve_v4.log`).
3. VS Code: 원격 창 "Developer: Reload Window" → 상태 표시줄 "clangd Rerank" 확인 → C/C++ 파일에서 자동완성. 서버가 없으면 2단계 순서로 즉시 대체된다.
   측정하려면 설정 `clangdRerank.recordStats`를 켜고 한참 쓴 뒤 "clangd Rerank: Show usage statistics".
4. 학습 재현: GPU가 비어 있을 때(`/usr/lib/wsl/lib/nvidia-smi`) scratchpad에서 `./train_v4.sh`(5h19m) → `clangd_test/eval_full.sh ext/kev/runs/clangd-0.8b-v4 v4`(13분) → `python3 -I clangd_test/summarize_compare.py kev_data v2e1 v3s3 v4`.

## Claude API 실험·식별자 생성 준비 (2026-11-02)

`docs/claude_api_and_ident_gen.md` 참고. 스크립트: `scripts/claude_eval.py`(+`run_claude.sh`, 키는 `claude.env`), 모든 자리를 모으는 `scripts/collect_newident.py`(cand/decl/miss/new 분류, `collect_auto.py` 의 `COLLECT_SCRIPT` 로 호출), 생성 채점 `scripts/gen_report.py`.
`eval_rerank.py report` 는 `RERANK_FILE`/`RERANK_LABEL` 로 다른 재정렬기 결과도 찍는다. 스모크(CLI11 tests 80곳): 후보에 정답 없는 자리 32% 중 실제 선언 자리(decl)는 7.5%, 나머지는 매크로·헤더 누락(miss).

`claude_eval.py compare <dir>`: clangd·Jev·Claude 모델별 R@1/MRR/R@5, 종류별 R@1, 지연, 실제 토큰·비용을 한 표로(2026-11-02 추가; 실행은 키 대기).

### Haiku 5.5 재정렬 결과 (2026-11-02, CLI11 266곳, effort low, 문맥 40줄, 후보 60)

R@1 0/1/2글자: clangd 18.0/55.6/79.3, Jev 69.9/87.6/91.4, **Kev v4 73.7/89.1/93.6**, Haiku 5.5 58.3/82.0/90.6.
종류별 0글자(clangd/Jev/Kev v4/Haiku): member 24/76/68/64, scope 10/86/64/**83**, ident 19/62/79/**48**.
Haiku는 scope(`::`)에서는 Jev 수준이지만 ident(가장 많은 종류)에서 크게 약하다: 틀린 80건 중 61건이 직전에 쓴 지역 변수(`app` 등)를 문맥과
무관하게 다시 고른 경우. 지연 중앙값 1.6초/p90 3.6초로 대화형 완성에는 못 쓴다(Kev 로컬 65ms, Jev 177ms).
비용 실측: 요청당 입력 1,989·출력 116 토큰(적응형 사고 포함) → 798요청 $0.205, 1,000요청당 $0.26 (Jev $0.07, Kev 0).
같은 토큰으로 환산하면 Sonnet 5.5 약 $4.1, Opus 5.5 약 $8.3/CLI11 세트(동기 정가). 표 `results/compare-claude-cli60.txt`.
결론: 값싼 범용 LLM(Haiku)은 0글자에서 Kev v4보다 15%p 낮고 20배 느리다. 상한 측정은 Opus(CLI11 $8)로 한 번 더 할 가치가 있다.

### 식별자 생성 실험 (2026-11-02~03)

**(1) 후보 없이 생성 → 후보에 대응(genmatch)이 후보 주고 고르기보다 낫다.** Haiku CLI11 0글자 R@1: rerank 58.3 → genmatch **74.1** (Kev v4 73.7, Jev 69.9),
비용은 $0.205 → $0.079 (입력 1,989 → 820 토큰). 후보 60개 목록이 작은 LLM에겐 오히려 방해였다. 신선셋 cand 2,559곳에서는 genmatch 68.4%
(Kev v4 는 eval_fresh60 에서 76.8%, 자리 집합이 달라 참고치). `claude_eval.py genmatch`, 표 `results/compare-claude-cli60-genmatch.txt`.

**(2) 선언 자리 비율은 10%.** 신선셋 38 저장소 + CLI11/cxxopts/lz4 (miss 50% 넘는 6개 제외) 4,284곳: cand 60.3 / miss 26.3 / **decl 9.9** / new 3.4%.
miss(전에 나온 이름인데 후보에 없음)는 헤더·매크로 등 clangd 설정 문제가 대부분이라 생성보다 설정으로 풀 일이다.
생성 평가 세트 `eval_data/eval_gen_fresh/` 3,723곳(신선셋만; cand 2,223 / miss 1,001 / decl 357 / new 142), 수집기 `collect_newident.py`.

**(3) 생성 정확도 (exact@1, 0/1/2글자; `results/gen-fresh-haiku.txt`)**

| 자리 | n | 최근 식별자 복사 | 타입→이름 규칙(`gen_typeheur.py`) | Qwen3.5-0.8B-Base 그대로(`gen_qwen.py`) | Haiku 5.5 generate |
|---|---|---|---|---|---|
| decl(새 이름 선언) | 357 | 0.8 / 15.4 / 24.9 | 10.6 / 12.9 / 13.2 | 34.7 / 48.7 / 56.3 | **47.9 / 59.7 / 62.7** |
| new | 142 | 0 / 0.7 / 0.7 | 0 / 0 / 0 | 26.1 / 44.4 / 50.7 | 63.4 / 66.9 / 74.6 |
| miss | 1,001 | 1.2 / 39.7 / 53.5 | - | 47.8 / 68.0 / 74.5 | 65.7 / 74.9 / 77.8 |
| cand(clangd 1위 20.1/51.5/68.7) | 2,223 | 3.9 / 48.4 / 64.8 | - | 53.7 / **77.3 / 82.8** | 62.0 / 69.4 / 68.9 |

exact@1, 접두어 0/1/2글자, 2026-11-03 전체 실행 완료. Haiku exact@5 는 decl 64.7/73.1/79.8. 새로 선언하는 이름의 절반을 문맥만으로 정확히 맞힌다. 비용 11,169요청 $1.44, 지연 1.25초.
절약 타수(`gen_report.py` 열, 5위 안에 있으면 남은 글자 - 고르는 비용): decl 0글자 남은 8.0자 중 Haiku 3.7자, Qwen 2.3자, 규칙 0.6자.
- 타입→이름 규칙(JetBrains 식, 모델 없음)은 `adm_context_t* context` 꼴만 맞히고(10%), `size_t from`·`GameState root` 처럼 문맥을 읽어야 하는 이름은 못 한다. 모델이 규칙의 4.5배 → 규칙만으로는 부족.
- Qwen 기반 모델(파인튜닝 전, 빔 5, 접두어 제약 생성)은 0글자에서 Haiku 의 7할(decl 34.7 vs 47.9), 1~2글자에선 격차가 줄고 cand 에선 Haiku 를 앞선다(제약 생성 효과).
  0글자 빈 응답 21/357(decl)·360/2,223(cand) 은 `)`·`0` 같은 비식별자 토큰이 빔을 채운 디코딩 문제 → `gen_server.py` 는 첫 토큰을 식별자로 제한한다. 건당 0.53초(HF generate 경로).
- decl 357곳 구성: 변수·매개변수·멤버 288(81%), 함수명 55(15%), `juce::` 같은 scope 오분류 14(4%). `if (_lock && xSemaphore...` 같은 매크로 미해석 자리도 섞여 있어 분류기 손질이 필요하다.

**(4) 전체 위치 기준 정답률 (후보에 정답 없는 자리까지 포함, 신선셋 3,723곳)**: 0글자 clangd 12.0% → Haiku 생성 1위 61.7%, genmatch 재정렬+생성 60.2%;
2글자 42.4% → 75.7%(선언 문맥·접두어 맞는 후보 없을 때만 생성 삽입하면 77.4%). 생성이 붙으면 "후보에 정답 없음"으로 깎이던 몫이 대부분 회복된다.

### Namer v1 학습과 문맥 보강 (2026-11-03)

모델 이름: 재정렬 = **Sorter**(Kev-0.8B v4), 생성 = **Namer**(Qwen3.5-0.8B-Base + LoRA).

- 데이터: `scripts/collect_decl.py`(tree-sitter, clangd 불필요)로 학습 소스 241 저장소에서 선언 자리 147,180건(저장소당 800·이름당 5·파일당 40 상한; local 58k/param 54k/field 25k/global 9k).
- 학습: `scripts/train_namer.py`(HF transformers+peft, LoRA r16, lr 1e-4, 1 epoch 60,000건, 왼쪽 패딩 + `logits_to_keep` 으로 이름 토큰만 손실, 검증 저장소 10개 분리). 53분. Sorter 서버와 GPU 를 같이 써도 재정렬 중앙값 87ms, p90 150ms.
- 문맥 보강: `scripts/ctx_enrich.py` — 커서 앞 40줄 바깥의 같은 파일 선언을 `// earlier in this file: ...` 한 줄로 요약해 프롬프트 앞에 붙인다(표준 라이브러리만, 커서 뒤 안 봄). 프록시 `full_before()` 가 파일 시작~커서(최대 `RERANK_GEN_MAX_LINES`=3000줄)를 보내고 `gen_server.py` 가 요약한다(`--no-enrich` 로 끔). `gen_qwen.py --src-root --enrich` 로 평가.

신선 decl 357곳 exact@1 (0/1/2글자; 부분집합 `eval_data/eval_gen_fresh_decl`, new 142곳은 괄호):

| 모델 | 보강 없음 | 보강 있음 |
|---|---|---|
| Qwen 기반 | 34.7 / 48.7 / 56.3 (new 26.1) | 36.7 / 51.5 / 58.5 (27.5) |
| Namer v1 | 35.0 / 48.5 / 55.2 (31.0) | **37.0 / 49.9 / 57.7** (31.7) |
| Haiku 5.5 | 47.9 / 59.7 / 62.7 (63.4) | - |

LoRA 는 1위 정확도를 못 올리고(exact@5 41.5→47.9, 빈 응답 21→0 만 개선), 보강은 +2%p 로 작지만 전 열에서 일관됐다. 격차는 모델 크기에서 온다고 본다.
공개 수치와 비교하면: Copilot 인라인 제안 수락률 27~30%(Ziegler 2022; 한 줄 전체), Pythia(IntelliCode, Python 멤버만) top-1 71%/top-5 92% ↔ Sorter 77%/95%, DIRTY 변수명 복원 66%(함수 전체를 보고).
다음 후보: 더 큰 기반 모델(1.5B/4B) 학습 없이 측정, 보강 프롬프트로 Namer 재학습.

## 다음 할 일

확장 체감 테스트와 실사용 R@1 수집(v4 서버로) → 후보에 정답이 없는 자리(27~46%)용 식별자 생성 항목,
프롬프트에 프로젝트 빈도 힌트를 넣는 변형, 접두어별 독립 2단계 세트 재측정, 사용자 분야 주제 추가 수집, (막히면) 인코더 방식(skundu42/kev) 검토.
