# 밤샘 자동 작업 계획 (2026-10-26 밤) — 사용자 지시: "밤새서 계속 알아서 작업 다 해놔라"

컨텍스트가 압축돼도 이 파일을 보고 이어 간다. 완료한 항목은 [x]로 바꾼다.

## 제약
- Bartimaeus_app 코드는 절대 쓰지 않는다 (사용자 지시).
- kev.serve 실행은 권한 검사에 막힘 → 서빙 지연 측정은 아침에 사용자에게 부탁.
- Jev는 공개 코드 평가에만, run_jev.sh(허용 규칙 있음)로만. 소액.
- 학습 설정은 내가 정한다: 1 epoch → 검증 오르면 --init_from 으로 1 epoch 더.

## 경로
- scratchpad: /tmp/claude-1000/-home-bartimaeus-projects-study-claude/9089f54d-d9d0-4cc5-bee8-274e98bb2bcd/scratchpad
- Kev 저장소/venv: ext/kev (.venv), 학습: PYTHONPATH=. .venv/bin/python -m kev.train ...
- 스크립트: clangd_test/{eval_rerank.py,to_kev_jsonl.py,kev_local_eval.py,compare_models.py,sweep.py,collect_auto.py,
  stage1_ranker.py(=2단계 LightGBM),stage2_reorder.py,clangd_rerank_proxy.py,proxy_smoke.py}
- 샘플: train_out/(7개+CLI11), train_out2/(새 21개; 시험 예약 lz4·entt·cxxopts), 1차 모델 ext/kev/runs/clangd-0.8b
- 보존 폴더: ~/projects/clangd-rerank/
- 조사 문서: https://claude.ai/artifact/PwnEfkhiMjvhugkdv1ofsu (doc id b9cf1770-c54d-4ddd-a175-2c696173a7b0, node 48938642-4424)

## 진행 중 (백그라운드)
- [x] 수집 collect_auto.py → train_out2/ 완료 (21개, 유효 합계 ~11,000곳; entt는 68곳뿐)
- [x] 탐색 sweep.py 완료 02:45 → sweep/results.tsv. 0글자 R@1(CLI11, 1 epoch): lr5e-5 65.4% > head2e-4 61.7% > cands30 49.8% > smooth 48.1% > lr2e-5 46.2% > ctx20 44.4% > ctx80 42.6% > lr1e-5 38.0% > cands100 33.1%. 결론: lr 5e-5 채택, 40줄/60개 유지.

## 할 일
- [x] A. 학습셋 v2 = 24개 소스(kev_data/train_v2_sources.txt) → kev_data/train_v2.jsonl 38,674건 (CTX 40, cands 60). 탐색이 다른 형식을 고르면 to_kev_jsonl.py 로 다시 만든다(초 단위).
- [x] B. 시험셋 eval_lz460(563곳), eval_entt60(59곳), eval_cxxopts60(143곳) + Jev 기준값 완료. Jev 0글자 R@1: lz4 62.7%, entt 74.6%, cxxopts 73.4% (clangd 17.4/25.4/18.2). Kev 시험 파일: kev_data/test_{lz4,entt,cxxopts}.jsonl
- [x] C. 2단계 v2 완료(24개 소스 41,481질의, 110트리) → 모델 train_out/stage2_v2_lgb.txt. 0글자 recall@60: CLI11 95.0%, lz4 95.1%, entt 98.5%, cxxopts 100% (clangd 기본 83/?/?/?). recall@30: 92.5/90.3/98.5/96.2. 2단계 단독 R@1 0글자 31.7/21.0/57.4/31.4.
- [x] G. 프록시에 2단계 삽입 완료(STAGE2_MODEL, RERANK_SKIP3_TYPED=2). 테스트: v. → 2단계 2.4ms + Jev 277ms, push_back 1위; v.pu → 2단계만 7ms.
- [x] D. 학습 완료 04:50 (37,080건 학습, 121분). 평가 task bhrry8zmy → kev_data/compare-v2e1.txt. 원래: train_v2.jsonl 38,674건, lr 5e-5, 1 epoch → ext/kev/runs/clangd-0.8b-v2-e1 (task bwcdui4md, 로그 kev_data/train_v2_e1.log, 예상 ~130분 → 05:00). 끝나면 clangd_test/eval_ckpt.sh <ckpt> 로 CLI11+시험셋 4개 평가.
- [x] E. 완료 07:14. v2-e2는 0글자 R@1이 CLI11 65.8/fmt 81.8/lz4 65.0/entt 91.5/cxxopts 79.0 → 5개 중 4개 하락 → **v2-e1 최종**. 원래: --init_from v2-e1, lr 3e-5, seed 2 → runs/clangd-0.8b-v2-e2 (task bnuh52yzh, 로그 kev_data/train_v2_e2.log, ~07:00 완료 예상) → eval_ckpt.sh ... v2e2 → 더 나은 쪽을 최종으로.
- [x] F. 완료(v2e1 결과는 기록 참조). 서빙(serve_bench-v2e1.txt): 중앙값 50ms p90 55~63ms, K30/K60 차이 1ms; 프록시 끝까지 72~93ms(첫 요청 ~200ms). 준비(03:05): 2단계 v2로 거른 세트 eval_{cli,fmt,lz4,entt,cxxopts}_s2k{60,30}/ + kev_data/s2k{60,30}_<proj>.jsonl. 다루는 위치: CLI11 303/295 of 319, fmt 533/520 of 550, lz4 623/593 of 657, entt 67/67 of 68, cxxopts 156/150 of 156. 실행: clangd_test/eval_s2.sh <ckpt> <태그> → clangd_test/stage_f_report.py <태그>. (스모크: 탐색 lr5e-5 모델, entt K30 0글자 80.6%)
  평가 명령: clangd_test/eval_ckpt.sh <ckpt> <태그> (CLI11+시험셋 4개, 결과 kev_data/compare-<태그>.txt)
- [x] H. 07:25 최종 체크포인트 models/kev-0.8b-clangd-v2, 시험셋·s2 세트·결과 복사, README 전면 갱신. 03:10 스크립트·2단계 모델(v1/v2)·sweep 결과·train_v2_sources.txt 복사함. 남은 것: 최종 체크포인트, 시험셋/s2 세트, README 갱신. 보존: 최종 체크포인트·2단계 모델·스크립트·결과를 ~/projects/clangd-rerank/ 에 복사, README 갱신.
- [x] I. 07:40 완료(문서 rev 11, 메모리 갱신, 아침 보고). 조사 문서에 "2차 실험 결과" 섹션, 메모리 갱신, 아침 보고문 작성(사용자에게 부탁할 것: kev.serve 띄워서 서빙 지연 측정).

## 권한 (사용자가 settings.local.json 에 허용): serve_kev.sh <체크포인트> [포트], run_jev.sh <eval_dir>
- 서버는 첫 요청 때 triton 커널 컴파일로 10초 넘게 걸림 → 띄운 뒤 워밍업 요청 1~2번 필요.
- 1차 모델 서빙 경로(bf16) 측정(CLI11 150건): 왕복 중앙값 82ms, p90 104ms, 최소 55ms, R@1 71.3%(0~2글자 섞임). 프록시 전체(2단계 2.5ms + 3단계): 70~170ms.
- 최종 모델이 나오면 serve_kev.sh 로 다시 띄워 같은 측정 반복 (F 단계).

## 기록
- v2-e1 (05:05, kev_data/compare-v2e1.txt) 0글자 R@1 clangd/학습후/Jev: CLI11 18.0/67.3/69.9, fmt 19.6/83.2/62.4, lz4 17.5/68.4/60.9(389곳; 312건 ContextOverflow 제외), entt 25.4/93.2/74.6, cxxopts 18.2/77.6/73.4.
  1글자: CLI11 88.0(Jev 87.6), fmt 94.1(83.6), lz4 86.4(83.7), entt 98.3(100), cxxopts 88.1(87.4). 2글자: 91.4/94.6/89.9/98.3/89.5.
  약점: `::` 뒤(scope) CLI11 60.3 vs Jev 86.2, cxxopts 64.1 vs 82.1. 학습 소스에 시험 프로젝트 파일 없음 확인(파일명 기준). 주의: 공개 프로젝트라 베이스 모델 사전학습에 포함됐을 수 있음(모든 공개 평가의 공통 한계).
  lz4는 긴 줄 때문에 fp32 평가 경로(1400 토큰)에서 18%가 넘침 → 프록시에 토큰/글자 예산 자르기 필요.
- F(v2e1) 완료 05:30 → kev_data/stage_f-v2e1.txt (stage_f_report.py v2e1). 전체 위치 기준 0글자 정답률 clangd → 2단계K60+Kev: CLI11 15.0→62.1, fmt 15.3→78.0, lz4 14.9→53.1(K30 60.3; 넘침 영향), entt 22.1→86.8, cxxopts 16.7→75.0.
  K30 vs K60: 전체 기준 거의 같음(±0.5), K30이 빠름. '2글자부터 2단계만' 규칙은 이제 손해(CLI11 84.8 vs 93.4, fmt 83.1 vs 92.1) → 프록시 기본 RERANK_SKIP3_TYPED=0 으로 바꿈.
  주의: s2 세트는 세 접두어 모두 K 안에 든 위치만 남겨서 접두어별로는 보수적인 수치(1·2글자는 실제 다루는 위치가 더 많음).
- 서빙 측정 스크립트 clangd_test/serve_bench.py <kev_jsonl> [N] [url] 준비 (E 끝나고 serve_kev.sh 로 최종 모델 띄워 K60/K30 측정).
- 2단계 첫 결과(CLI11 319곳, 0글자): recall@60 83.4→95.9%, R@1 15.0→31.3%. 2단계+3단계 전체 기준 0글자 44.9→50.7%. 2글자부터는 2단계만 84.3% ≈ +Kev 85.0%.
s2 pending block: mqq9rv2mh31.6177 (doc rev 10)

## 아침 추가 (2026-10-27 08:00~) — `::`(scope) 약점 보강
- 진단: 학습 위치 종류 ident 10,712 / member 1,568 / scope 1,547 (11%). CLI11 scope 0글자 35/58; 오답 대부분 `CLI::` 뒤 정답 App 대신 Config/Option → "이 프로젝트에서 흔한 이름" 지식 부족.
- 공짜 실험(CPU, 스크립트 clangd_test/blend_eval.py, projfreq_eval.py): 2단계 점수 섞기(a=0.5) 시험셋 +1%p 안팎, scope 거의 안 오름. 프로젝트 전체 식별자 빈도 사전확률(b=0.5~1.0)은 scope만 오르고(CLI11 60→64, cxxopts 64→72) 전체는 하락 → 채택 안 함.
- [중단] v3 재학습 08:05 시작 → 08:15 사용자 요청으로 중단(80/5731 스텝), 체크포인트 없음. 사용자: 여기서 고정(v2-e1 최종)하고 정리. 재개하려면 같은 명령. 원래: scope 위치 3배 복제(train_v2_scope3.jsonl 47,576건), 그 외 v2 레시피 동일 → runs/clangd-0.8b-v3-scope3 (task bi1c5vh5m, 로그 kev_data/train_v3_scope3.log, ~2.5h). 끝나면 eval_ckpt.sh ... v3s3 → compare-v3s3.txt, scope 행 비교.
- 다음 후보(이번에 부족하면): 후보 설명에 프로젝트 빈도 힌트("App — used 212× in project")를 넣어 모델이 배우게 하는 v4; scope 많은 프로젝트 추가 수집.
- 13:12 v3 scope3 재학습 재시작 (task biepqlq9p, 0.19s/rec, ~15:40 완료 예상). 끝나면 eval_ckpt.sh runs/clangd-0.8b-v3-scope3 v3s3 → compare-v3s3.txt 와 v2e1 scope 행 비교.
- 13:20~ VS Code 확장 v0.1 시작: ~/projects/clangd-rerank/vscode-extension/ (package.json, src/extension.ts, resources/{proxy, stage2_lite.py, stage2_v2_lgb.txt}). 프록시 2단계를 stage2_lite.py(표준 라이브러리)로 교체·검증. Node 미설치(nvm 설치 스크립트는 권한 거부) → 사용자에게 설치 요청.

## 데이터 다양화 (2026-10-27 오후) — "보통 개발자 코드"
- 작업 폴더 이전: tmpfs(/tmp 12G) 96% → sweep, train_src, train_out*, jevenv, eval_* 를 ~/work/clangd-rerank/ 로 옮기고 scratchpad에 심볼릭 링크. ext/kev(7G)·kev_data 는 v3 학습 끝난 뒤 옮긴다(로그 fd 때문).
- GitHub 수집(clangd_test/collect_github.py): 24주제 × ≤12개, 별 5~500, 2022+ 갱신, 허용 라이선스만, library/framework/sdk 제외 → 252개 저장소 7.2G, ~/work/clangd-rerank/train_src2/ + manifest.jsonl. (assignment 0, coursework 1, university 6, gtk 5 는 조건 맞는 게 적었음)
- code_contests(deepmind, HF) C++ 풀이 917파일 → train_out3/codecontests 1,928위치. scope 10개뿐(using namespace std) → `::` 보강엔 무용, 다양성용으로 ≤1,000개만 쓸 것.
- 추출: train_out3/ (pass1 72개 task bzoouz1r8, pass2 180개 task bhzbf9n7c). 끝나면 유효 위치 수 집계 → 시험용으로 몇 개(예: 주제별 1개) 떼어 두고 v4 학습셋 = v2 24소스 + 새 소스.

## v4 계획 (2026-10-27 14:20 기록) — 사용자 지시: 데이터 편향 주의
1. pass2(180개) 끝나면 train_out3 전체 집계: 주제별 프로젝트 수·위치 수·member/scope 비율 표 (results/에 저장).
2. 응용 코드 시험셋: 주제별 1개 저장소(유효 위치 100개 이상, 중간 크기)를 학습에서 제외 → eval_app60 (clangd 상위 60, 커서 뒤 제외). 기존 라이브러리 시험셋(fmt·lz4·entt·cxxopts)과 따로 보고.
3. 학습셋 v4 = v2 24소스(라이브러리, 그대로) + 응용 저장소(프로젝트당 상한 N, 주제당 비중 비슷하게) + codecontests ≤1,000위치. N은 총 학습 레코드가 8만~12만(학습 4.5~7시간)이 되게 정한다(후보: N=120). scope 비율이 v2(11%)보다 낮아지면 scope 가중.
4. 중복 검사: 학습·시험 파일 해시 중복, 번들 라이브러리(imgui/stb/glm 복사본) 제외 확인.
5. v3(scope 3배) 결과를 보고 v4에 scope 가중을 넣을지 결정 → v4 학습(lr 5e-5, 1 epoch, Kev 베이스에서) → 시험셋 5개 + 응용 시험셋 평가 → 최종 선택 → 확장 기본 모델 교체.
6. 병행: Node 설치되면 확장 컴파일·vsix·원격 설치·실사용 테스트. 프록시에 "사용자가 고른 항목 순위" 기록 기능 추가.
- 15:05 v4 데이터 완료: 학습 219 응용 프로젝트(CAP 100/프로젝트, codecontests 1,000) 21,516위치 + v2 24소스 → kev_data/train_v4.jsonl 99,308건 (소스 목록 train_v4_sources.txt, 243개). member 10.1% / scope 11.0%. 제외: 시험 라이브러리 번들 파일 300, 중복 파일 650.
  응용 시험셋: 주제별 1개 저장소 23개(train_out3/app_test_pick.json) → eval_app/ 7,046위치 (test_app.jsonl 20,053건), 부분집합 eval_app_sub/ 2,070위치 (test_app_sub.jsonl 5,911건). samples 에 "project" 필드 추가됨.
  주의: samples 의 file 은 프로젝트 상대 경로 (절대 경로 아님) — projfreq_eval.py 의 현재 파일 제외는 동작 안 했음(결론엔 영향 작음).
  v2e1 응용 기준값 측정 중 task b39fga2jq → pred-v2e1-test_app_sub.jsonl → compare_models.py eval_app_sub/samples.jsonl kev_data/test_app_sub.jsonl - <pred>
  v4 학습 예상: 99k건 ≈ 5.5시간(단독). v3 끝나고 ext/kev·kev_data 를 디스크로 옮긴 뒤 시작.
- 15:30 응용 코드 시험셋(eval_app_sub 1,858곳 교집합, 상위60/40줄) 결과 → results/compare-v2e1-app.txt: 0글자 R@1 clangd 29.2 / v2e1 77.3 / Jev 67.4; 1글자 65.1/91.2/86.4; 2글자 79.3/94.4/88.6. scope 23.8/75.1/71.9, member 33.1/70.2/74.2, ident 29.4/78.3/66.2. 2단계 v2 recall@60 0글자 91.0→98.7%. Jev 비용 약 $0.42(10.0M 토큰). 결론: 라이브러리로 배운 모델이 응용 코드에도 잘 일반화(라이브러리 시험셋과 같은 수준). v4의 목적은 "추가 상승 + 분포 폭 넓히기"로 재정의.
- 16:11 v3(scope 3배) 학습 완료(13:12 시작, 2h59m, 마지막 loss 0.1~0.4) → runs/clangd-0.8b-v3-scope3. 16:12 평가 시작(task bjqwf6jc5, clangd_test/eval_full.sh = eval_ckpt.sh 5셋 + 응용 eval_app60_sub) → kev_data/compare-v3s3.txt, compare-v3s3-app.txt, 로그 kev_data/eval_full-v3s3.log.
  병행: ext/kev → ~/work/clangd-rerank/ext/kev 로 rsync(venv 는 uv 관리 python 을 가리키는 심볼릭 링크라 경로만 심볼릭 링크로 유지하면 재생성 불필요). 평가 끝나면 rsync --delete 한 번 더 → scratchpad/ext/kev 를 심볼릭 링크로 교체.
- 16:14 Node 설치: nodejs.org 공식 tarball(v24.22.1 LTS) 을 scratchpad/node_dl/node.tar.xz 로 받아 SHA256 확인(SHASUMS256.txt 일치). 압축 해제·실행은 권한 검사(외부 코드)에 막힘 → 사용자가 직접: `tar -xJf <scratchpad>/node_dl/node.tar.xz -C ~/.local && ln -sfn ~/.local/node-v24.22.1-linux-x64 ~/.local/node` 후 PATH 에 ~/.local/node/bin 추가. 그 다음 vscode-extension 에서 npm install → npm run compile → npx vsce package.
- 16:25 프록시 실사용 측정 기능 추가(RERANK_STATS): completion 응답을 돌려준 자리(uri, 줄, 단어 시작 col)를 기억하고 didChange 를 따라가며(윗줄 편집 시 위치 이동, 단어 편집은 유지, 다른 곳 편집·저장·닫기·다른 자리 요청이면 끝) 사용자가 결국 쓴 식별자와 그 항목의 clangd/2단계/최종 순위를 JSONL 로 적는다(친 글자 0·1·2 단계별 한 줄; 코드 본문은 적지 않음). 집계 rerank_stats.py. 단위 시험 test_sites.py 7개 통과, proxy_smoke(런처 경유) 통과. 확장: 설정 clangdRerank.recordStats(기본 끔) + 명령 "Show usage statistics". scripts/·resources/ 동기화.
- 16:30 v3(scope 3배) 라이브러리 시험셋 결과(compare-v3s3.txt), 0글자 R@1 v2e1→v3s3: CLI11 67.3→72.2(scope 60.3→65.5, ident 68.4→75.3, member 72.0→70.0; 1글자 88.0→86.8), fmt 83.2→82.2, lz4 68.4→66.3(member 66.0→72.3, ident 68.7→65.5), entt 93.2→94.9, cxxopts 77.6→75.5(scope 64.1→64.1). n 가중 합계 1,285곳: 75.3→75.2 (동일). 결론: scope 3배는 전체적으로 중립(세트 간 ±2~5%p 는 소표본 잡음 수준), cxxopts scope 는 그대로 → 응용 시험셋 결과까지 보고 v4 가중 여부 결정(기본: 가중 없이 자연 분포 11% 유지).
- 16:27 v3 응용 시험셋(1,858곳) 결과(compare-v3s3-app.txt): 0글자 R@1 v2e1 77.3 → v3 76.3, 1글자 91.2→91.1, 2글자 94.4→94.2; scope 75.1→76.8, member 70.2→69.5, ident 78.3→76.9. 결론: scope 3배 복제는 scope 를 +1~5%p 올리지만 나머지가 그만큼 내려 전체 중립~소폭 하락 → **v4 는 가중 없이 자연 분포 유지**. (eval_full.sh 의 응용 samples 경로를 eval_app_sub 로 고침: eval_app60_sub 는 Jev 결과 전용.)
- 16:27 ext/kev → ~/work/clangd-rerank/ext/kev 이전 완료(36,588 파일, 8.63GB 일치), scratchpad/ext/kev 는 심볼릭 링크. tmpfs 9.4G → 1.3G. train_v3_scope3.log 도 디스크로.
- 16:28 **v4 학습 시작**(task bdtqk4fxb, train_v4.sh): kev_data/train_v4.jsonl 99,308건, lr 5e-5, 1 epoch, batch1×accum8, bf16, max_state 1400, Kev 베이스 → ext/kev/runs/clangd-0.8b-v4, 로그 kev_data/train_v4.log(디스크). 예상 ~12,400 스텝, 0.19~0.23 s/rec → 21:40~22:50 완료. 끝나면 clangd_test/eval_full.sh ext/kev/runs/clangd-0.8b-v4 v4 → compare-v4.txt, compare-v4-app.txt → v2e1 과 비교해 최종 선택.
- 16:40 **v4 학습 중단**(사용자: "v4는 나중에 하자"). 약 12분(~700/12,414 스텝) 진행, LoRA 실행이라 중간 체크포인트 없음 → 재개는 `train_v4.sh` 로 처음부터(~5.5h). GPU 비움. Node v24.22.1 설치됨(사용자 실행) → 확장 컴파일 진행.
- 16:45 확장 컴파일(tsc 오류 0) → clangd-rerank-0.1.0.vsix(9 파일, 166KB) → 원격 서버(Stable-e646868)에 code-server --install-extension 으로 설치(~/.vscode-server/extensions/bartimaeus.clangd-rerank-0.1.0). 사용자가 VS Code 창을 다시 불러오면 활성화. Kev 서버(v2-e1, 8009) 띄움(task bpbostrzm, 로그 ~/work/clangd-rerank/kev_data/serve_v2e1.log).
- 16:50 **중간 정리**(사용자: 여기까지 하고 나중에 재개). 프록시→2단계→Kev 서버 스모크 통과(v. 뒤 push_back 1위, 첫 요청 1052ms 워밍업). README.md 에 "3차 진행" + "재개 방법" 추가, 응용 시험셋 eval_data/ 보존, scripts/ 전부 동기화, scripts/restore_scratchpad.sh 추가. Kev 서버(task bpbostrzm)는 세션과 함께 꺼짐. 재개 시 할 일: VS Code 창 다시 불러와 체감 테스트·recordStats 수집 → v4 학습(train_v4.sh) → eval_full.sh v4 → 최종 선택.

## 4차 (2026-10-28 새벽) — v4 학습 재개 (사용자: "학습이나 해")
- 00:35 GPU 비어 있음(1.9GB) 확인 → `./train_v4.sh` 재시작(setsid, 로그 kev_data/train_v4.log). 12,036 스텝(99,308건 중 3,021건 문맥 초과로 제외 → 96,287건 /8), 0.21 s/rec → 약 5.7h, 06:20 전후 완료 예상.
- serve_kev.sh 버그: `cd ext/kev` 뒤에 상대 경로를 그대로 넘겨 `ext/kev/runs/...` 를 못 찾고 runs/smoke 로 떨어져 죽음 → cd 전에 절대 경로로 바꾸도록 수정(보존 폴더 scripts/ 에도 복사). 체감 테스트는 사용자가 자러 가서 서버는 다시 껐음(학습에 GPU 전부 할당).
- VS Code 확장 상태: 어제 16:33 활성화·clangd.path 교체까지는 됐으나 clangd 는 그 직전에 뜬 것이라 아직 런처 미적용 → 창 다시 불러오기(Developer: Reload Window) 필요. 자정 전 vscode-clangd 쪽 "provider FAILED" 로그가 여러 번 있는데 원인 미확인(런처와 무관, 평범한 clangd).
- 학습 종료 후 자동 실행: `run_after_train_v4.sh`(kev.train 종료 대기 → eval_full.sh v4 → kev_data/compare-v4.txt, compare-v4-app.txt; 로그 kev_data/eval_full_v4.log).
- 05:54 학습 완료(5h19m, 12,036 스텝, 0.197 s/rec, 마지막 loss 0.28) → 05:55~06:08 eval_full.sh v4 자동 실행.
- **결과: v4 채택.** 0글자 R@1 v2e1→v4: CLI11 67.3→73.7, fmt 83.2→83.6, lz4 68.4→69.2, entt 93.2→91.5(n=59), cxxopts 77.6→82.5; 라이브러리 n가중 75.3→77.4; 응용 77.3→79.2(1글자 91.2→91.6, 2글자 94.4→95.1). 종류별 응용 member 70.2→76.2, scope 75.1→74.6, ident 78.3→80.1. v3 와 달리 전 항목이 고르게 오름 → 가중 복제보다 분포 폭 확대가 효과적. 표: kev_data/summary_v2e1_v3s3_v4.md (summarize_compare.py).
- 보존: models/kev-0.8b-clangd-v4, results/compare-v4*.txt, pred-v4-test_app_sub.jsonl, train_v4.log, summary_v2e1_v3s3_v4.md; README "4차 진행" 절, 재개 방법·확장 README 의 모델을 v4 로.
- 06:10 v4 서버(8009) 띄움(setsid, kev_data/serve_v4.log) → 확장 런처 경유 스모크 확인 → 아침 체감 테스트용으로 켜 둠.
