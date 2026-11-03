# Claude API 실험 + 식별자 생성 기능 준비 (2026-11-02)

상태: 서버·모델 모두 내려간 상태. API 키만 주면 아래 1장을 바로 돌릴 수 있고, 2장은 수집기·채점기까지 준비됐다.

## 1. Claude API 로 해볼 수 있는 것

준비된 것: `scripts/claude_eval.py`(anthropic SDK 2.3.0, `~/work/clangd-rerank/jevenv` 에 설치), 래퍼 `scripts/run_claude.sh`,
키 파일 `claude.env`(`claude.env.example` 복사, `.gitignore` 됨). `eval_rerank.py report` 가 `RERANK_FILE`/`RERANK_LABEL` 로 Claude 결과도 같은 표로 찍는다.

```bash
cp claude.env.example claude.env   # ANTHROPIC_API_KEY=... 채우기
scripts/run_claude.sh rerank eval_cli60 --dry-run          # 키 없이 토큰·비용 추정
scripts/run_claude.sh rerank eval_cli60 --limit 30         # 30곳 시범 (약 $0.2, Opus)
scripts/run_claude.sh rerank eval_cli60                    # 전체 → clangd vs Claude 표 출력
MODEL=claude-haiku-5-5 scripts/run_claude.sh rerank eval_fresh60
scripts/run_claude.sh generate eval_cli60                  # 후보 없이 식별자 맞히기
python3 -I scripts/gen_report.py eval_data/eval_cli60/samples.jsonl eval_data/eval_cli60/claude-opus-5-5-gen.jsonl
# 큰 세트는 배치(절반 가격, 보통 1시간 안): 
~/work/clangd-rerank/jevenv/bin/python -I scripts/claude_eval.py batch-submit rerank eval_data/eval_fresh60 --model claude-sonnet-5-5
~/work/clangd-rerank/jevenv/bin/python -I scripts/claude_eval.py batch-fetch  rerank eval_data/eval_fresh60 --model claude-sonnet-5-5
```

요청 설정: 문맥 40줄(Kev 와 동일), 후보 60개, 구조화 출력(JSON 스키마), effort low, 적응형 사고 그대로(끌 수 없음), 서버측 fallback 켬.
출력은 상위 10개 후보 이름 → 확률 0.5^순위로 바꿔 jev.jsonl 형식으로 저장(미언급 후보는 clangd 순서 유지).

비용 추정(--dry-run, 문자 수/3.6 근사; 키가 있으면 `--count-tokens` 로 보정):

| 세트 | 요청 | 입력 토큰 | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 | 배치 |
|---|---|---|---|---|---|---|
| eval_cli60 (266곳×3) | 798 | 0.88M | $5.9 | $3.0 | $0.15 | 절반 |
| eval_fresh60 (1,638×3) | 4,914 | 6.0M | $38.7 | $19.4 | $1.0 | 절반 |
| eval_app60_sub (1,873×3) | 5,619 | 6.6M | $43.3 | $21.7 | $1.1 | 절반 |
| generate eval_cli60 | 798 | 0.38M | $3.9 | $2.0 | $0.10 | 절반 |

실험 목록(우선순위 순):

1. **재정렬 상한선**: 라이브러리 5세트 + 신선셋에서 Claude(Opus/Sonnet/Haiku) R@1 을 clangd·Kev v4(76.8)·Jev(68.6)와 같은 표에. Jev 는 외부 결정 모델 하나였고, 범용 LLM 비교가 빠져 있었다. 먼저 Haiku 로 전 세트(약 $2), 그 다음 Opus 로 CLI11 만.
2. **scope(`::` 뒤) 약점 진단**: Kev 가 60% 대에 머문 자리를 Claude 가 맞히는지 종류별 표로 비교. 맞히면 지식 문제(모델 크기), 못 맞히면 데이터 문제.
3. **생성 상한선**: `generate` 로 후보 없이 식별자를 맞히는 비율(cand 자리에서 exact@1). 이게 높으면 생성 항목을 후보가 있는 자리에도 얹을 수 있고, 낮으면 선언 자리에서만 쓴다.
4. **선언 자리 생성 평가**: 2장 수집기로 만든 decl 세트에 `generate` → gen_report. 이게 생성 기능의 첫 수치.
5. **학습 데이터 라벨링**(후속): 선언 자리 학습 데이터에 Claude 가 만든 "그럴듯한 다른 이름"을 보조 라벨로 붙여 생성 모델 증강. 편향 주의([[feedback_training-data-bias]]).
6. (선택) 실사용 프록시 백엔드 `claude` 추가: 왕복이 1초 안팎이라 체감 비교용이지 제품용은 아니다.

주의: 공개 프로젝트는 Claude 사전학습에 들어 있을 수 있다 → 신선셋(2026-03 이후 생성) 결과를 기준으로 본다. 모델 ID 는 날짜 접미사 없이 `claude-opus-5-5` 처럼 쓴다.

### 실측 (Haiku 5.5, CLI11, 2026-11-02)
요청당 입력 1,989 토큰(드라이런 추정 1,100의 1.8배: 후보 60개의 detail 문자열이 토큰 밀도가 높다), 출력 116 토큰(중앙값 62, 최대 637).
798요청 $0.205. 0글자 R@1 58.3% (Kev v4 73.7, Jev 69.9). 결과 `results/compare-claude-cli60.txt`.
실측 토큰 기준 세트별 동기 정가: CLI11 798요청 Haiku $0.21 / Sonnet $4.1 / Opus $8.3; 신선셋 4,914요청 Haiku $1.3 / Opus $51; 응용 5,619요청 Haiku $1.4 / Opus $58.

### 모델별 성능·비용 비교 (`compare`)

```
MODEL=claude-haiku-5-5 scripts/run_claude.sh rerank eval_cli60      # 결과 eval_data/eval_cli60/claude-haiku-5-5.jsonl
MODEL=claude-sonnet-5-5 scripts/run_claude.sh rerank eval_cli60
scripts/run_claude.sh compare eval_cli60 --ref "Kev v4=73.7/89.1/93.6"
```
`compare` 는 clangd, jev.jsonl, `claude-*.jsonl` 전부를 같은 (위치, 접두어) 교집합에서 비교한다: R@1/MRR/R@5, 종류별 0글자 R@1,
오류·거부 수, 지연 중앙값/p90, 요청당 입·출력 토큰, 실제 비용(정가; 배치 건은 절반), 1,000요청당 비용, 전체 세트 환산 비용.
Kev v4 수치는 결과 파일 형식이 달라 `--ref` 로 기존 표(`results/compare-v4.txt` 등)의 R@1을 옮겨 적는다
(CLI11 73.7/89.1/93.6, 신선셋 0글자 76.8, 응용 0글자 79.2).
Jev 단가는 신선셋 실측(9.0M 토큰 $0.38 ≈ $0.042/M) 근사다.

## 2. 식별자 생성 기능 준비

### 왜
재정렬은 clangd 후보 안에 정답이 있을 때만 돕는다. 새 변수·함수 이름을 짓는 자리는 후보에 없으므로 "전체 위치 기준" 정답률이 깎인다
(README: CLI11 67.3 → 62.1, lz4 68.4 → 53.1). 그 자리를 생성 항목으로 메우는 것이 목표.

### 자리 분류 (`scripts/collect_newident.py`)
eval 세트는 정답이 후보에 있는 자리만 담았기 때문에 새 수집기를 만들었다. 모든 자리를 모으고 분류한다:

- `cand`: 0글자 후보에 정답 있음 (기존 평가 자리)
- `decl`: 앞 토큰이 타입처럼 보이고(식별자·`>`·`*`·`&`·auto 등) 뒤가 `= ; , ) ( { [ :` → 새 이름을 짓는 자리. **생성 대상**
- `miss`: 전에 나온 이름인데 후보에 없음 → 헤더 못 찾음·매크로(CHECK)·파싱 실패·후보 한도. 재정렬 대상도 생성 대상도 아니고 clangd 설정 문제가 대부분
- `new`: 그 외 처음 보는 이름 (문자열 안 등 잡음)

스모크(CLI11 tests 2파일 80곳): cand 67.5%, decl 7.5%, miss 23.8%, new 1.2%. 
Arduino 예제 프로젝트는 테스트 프레임워크 헤더가 없어 miss 80% → 이런 프로젝트는 수집에서 걸러야 한다(summary.txt 의 miss 비율로).
"27~46%" 로 적어 두었던 '후보에 정답 없음' 비율 중 실제 생성 대상(decl)은 그보다 훨씬 작다는 뜻이다. 프로젝트 여러 개로 다시 재야 한다:

```bash
COLLECT_SCRIPT=collect_newident.py MAX_FILES=6 EVAL_PER_FILE=50 python3 -I scripts/collect_auto.py ~/work/clangd-rerank/newident_out ~/work/clangd-rerank/train_src/CLI11 ~/work/clangd-rerank/train_src/fmt ...
```
(수집기는 clangd 만 쓰므로 GPU·모델 서버가 필요 없다. 파일당 50곳 × 3접두어 ≈ 1~2분.)

### 실측 (2026-11-02): 생성 상한, 선언 자리 비율, 기준선

**후보 없이 생성(generate)이 후보 주고 고르기(rerank)보다 낫고 싸다 (Haiku, CLI11 266곳).**
generate exact@1 0/1/2글자 70.7/74.4/82.0%, exact@5 84.2/89.8/93.2%. 추측을 clangd 후보에 대응시킨 `genmatch` 재정렬은
R@1 **74.1**/84.2/92.9% 로 rerank(58.3/82.0/90.6)보다 높고 Kev v4(73.7/89.1/93.6)와 0글자에서 같다. 종류별 0글자: member 72, scope 78, ident 73.
요청당 입력 820·출력 33 토큰, 세트 $0.079 (rerank $0.205). 후보 60개 목록이 Haiku 에겐 방해였다(최근 지역 변수를 고르는 편향).
지연은 1.3초로 여전히 대화형엔 못 쓴다. 표 `results/compare-claude-cli60-genmatch.txt`.

**선언 자리 비율 (`newident_fresh` 신선셋 38 저장소 + `newident_lib` CLI11/cxxopts/lz4, miss 50% 넘는 6개 제외, 4,284곳):**
cand 60.3%, miss 26.3%, **decl 9.9%**, new 3.4%. decl 뒤 문자 `=` 37%, `(` 16%, `,` 14%, `)` 13%, `;` 9%; 앞 토큰 `*`,`&`,int,`>`,auto,void,bool 순.
전체 위치 정답률 상한을 올리려면 decl 10%가 목표이고, miss 26%는 clangd 설정(헤더·매크로) 문제다.
fmt 는 train_src 에 없고, entt 는 clangd 응답 오류(Content-Length 없음)로 수집 중단 → 제외.
생성 평가 세트 `eval_data/eval_gen_fresh/` (신선셋만 3,723곳: cand 2,223 / miss 1,001 / decl 357 / new 142; 11,169요청).

**기준선 (`scripts/gen_baseline.py`, 문맥의 최근 식별자 5개 복사):** decl exact@1 0글자 0.8%, 1글자 15.4%, 2글자 24.9%. new 는 0~0.7%.
cand 자리에서도 0글자 3.9%(clangd 20.1%)라 '최근 것 복사'로는 안 된다.

**Haiku generate, 신선셋 3,723곳 (`results/gen-fresh-haiku.txt`):** exact@1 0/1/2글자 decl 47.9/59.7/62.7, new 63.4/66.9/74.6, miss 65.7/74.9/77.8,
cand 62.0/69.4/68.9 (clangd 1위 20.1/51.5/68.7). exact@5 decl 64.7/73.1/79.8. 11,169요청 $1.44, 입력 1,093·출력 40 토큰/요청, 지연 1.25초.
cand 자리 genmatch R@1 68.4/82.4/85.3 (member 77.4, scope 62.8, ident 67.7). 전체 위치 기준(후보 없는 자리 포함) 0글자 clangd 12.0 → 재정렬+생성 60.2,
2글자 42.4 → 75.7(선언 문맥·접두어 맞는 후보 없을 때만 삽입 77.4). README 표 참고.

**Qwen3.5-0.8B-Base 그대로 (`scripts/gen_qwen.py`, 빔 5, 접두어 제약 생성):** CLI11 40곳 스모크 exact@1 60.0/72.5/82.5% (Haiku 70.7/74.4/82.0).
파인튜닝 전 기반 모델이 Haiku 에 근접한다. 단 HF generate 경로 지연 중앙값 510ms(0글자는 더 짧음; 프록시용이 아닌 측정용 경로).

### 생성기 후보와 평가
`scripts/gen_report.py` 가 `{"i","k","guesses":[...]}` 형식이면 무엇이든 채점한다(분류×접두어별 exact@1/@5, 서브토큰 F1, 접두어 준수).
기준선(문맥에서 최근 식별자 5개 복사)은 decl 자리에서 exact@1 ≈ 0 이라 어떤 생성기든 이보다 나으면 된다.

1. Claude `generate` — 상한선·라벨링용 (1장 3·4번)
2. Kev 의 기반 모델 Qwen3.5-0.8B-Base 를 LM 헤드 그대로 greedy 로 10토큰 생성 (Kev 는 choice 전용이라 `kev.serve` 로는 안 되고 transformers 로 직접) — 지연 측정 포함
3. 2를 선언 자리 데이터로 LoRA 파인튜닝(state → gold 텍스트). 학습 데이터는 train_src/train_src2 를 `collect_newident.py` 로 다시 모아 decl 만 쓴다.

### 프록시 통합 설계 (`clangd_rerank_proxy.py`)
- 언제: 0~2글자 요청에서 (a) 선언 문맥(`is_decl` 과 같은 규칙을 커서 앞 텍스트에 적용) 이거나 (b) 친 접두어와 맞는 후보가 없을 때. 후보가 충분한 자리는 생성을 부르지 않아 지연을 아낀다.
- 무엇을: 완성 항목 하나를 맨 위에 끼운다. `label`=생성 이름, `kind`=1(Text), `sortText`="00000", `filterText`/`insertText`=이름, `detail`="생성", `preselect`=true. 생성 이름이 기존 후보와 같으면 그 후보를 위로 올리기만 한다.
- 지연: 생성은 10토큰 이내 → 0.8B 모델이면 서빙에서 30~60ms 예상. 재정렬과 병렬로 보내고 시간 초과면 생략(지금 규칙과 동일).
- 측정: recordStats 가 이미 '결국 쓴 식별자'를 적으므로 생성 항목의 실사용 채택률도 같은 파일에서 센다(`rank.final` 1 이면서 생성 항목인 경우를 표시하는 필드 하나 추가).
