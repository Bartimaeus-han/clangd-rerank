# clangd Rerank (v0.1, 개발 중)

clangd가 만든 자동완성 후보의 **순서만** 다시 매기는 VS Code 확장. 후보 생성은 clangd 그대로, 정렬은
2단계 특징 랭커(LightGBM, 2~3ms) + 3단계 결정 모델(파인튜닝한 Kev-0.8B 로컬 서버 또는 Jev API)이 한다.
빈 접두어에서 미리 선택된 항목이 정답인 비율이 clangd 기본 약 18%에서 67~93%로 올라간다(공개 프로젝트 5개 측정, 상위 README 참고).

## 동작 방식

1. 활성화되면 전역 저장소에 런처 스크립트(`clangd-rerank-launch.sh`)를 만들고 `clangd.path`를 그 경로로 바꾼다.
   원래 값은 기억해 두었다가 끌 때 되돌린다.
2. 런처는 `python3 -I resources/clangd_rerank_proxy.py <clangd 인자들>`을 실행한다. 프록시는 표준 라이브러리만 쓴다.
3. 프록시는 에디터와 clangd 사이에서 `textDocument/completion` 응답만 가로채 `sortText`를 다시 쓴다.
   모델 응답이 `timeoutMs` 안에 안 오면 2단계 순서, 그것도 없으면 clangd 순서를 그대로 돌려준다.
4. C/C++에서 `editor.suggestSelection`을 `first`로 맞춘다(VS Code의 "최근 사용" 기억이 재정렬을 되돌리지 않게; 끌 수 있음).

원격(WSL/SSH) 창에서는 workspace 확장으로 원격 쪽에서 돈다. Windows 로컬은 아직 지원하지 않는다(런처가 bash).

## 백엔드 설정 (`clangdRerank.backend`)

| 값 | 무엇이 필요한가 | 코드가 어디로 가나 |
|---|---|---|
| `local` (기본) | `python -m kev.serve --run <체크포인트> --port 8009` 로 띄운 Kev 서버 | 내 컴퓨터 안 |
| `jev` | TypeSafe API 키 (명령 "clangd Rerank: Set Jev API key") | 커서 앞 40줄 + 후보 이름이 api.typesafe.ai 로 전송 |
| `stage2Only` | 없음 | 어디에도 안 감 (정확도는 낮음) |

로컬 서버 띄우기(상위 폴더 `models/kev-0.8b-clangd-v4` 기준, jaredpalmer/kev 저장소 venv에서):

```bash
KEV_CUDA_GRAPHS=0 KEV_PREFIX_CACHE=0 python -m kev.serve --run ../models/kev-0.8b-clangd-v4 --port 8009 --host 127.0.0.1
```

## 개발

```bash
cd vscode-extension
npm install
npm run compile          # out/extension.js
# 디버그: 이 폴더를 VS Code로 열고 F5 (Extension Development Host)
npx vsce package         # clangd-rerank-0.1.0.vsix
code --install-extension clangd-rerank-0.1.0.vsix   # 원격 창이면 원격 쪽에 설치된다
```

`resources/`에는 프록시(`clangd_rerank_proxy.py`, `stage2_lite.py`)와 2단계 모델(`stage2_v2_lgb.txt`)이 들어 있다.
연구 폴더의 `scripts/` 쪽을 고치면 `resources/`로 다시 복사해야 한다.

## 명령

- clangd Rerank: Enable / Disable / Toggle (상태 표시줄 항목 클릭과 같음)
- clangd Rerank: Set Jev API key / Clear Jev API key
- clangd Rerank: Show proxy log — 요청마다 2단계·3단계 소요 시간과 상위 3개를 기록
- clangd Rerank: Show usage statistics — `clangdRerank.recordStats`를 켜 두면 자동완성 자리마다 "사용자가 결국 쓴 식별자"와 그 항목의 순위(clangd / 2단계 / 최종)를 전역 저장소의 `rerank-stats.jsonl`에 적는다(코드 본문은 적지 않음). 이 명령이 친 글자 수별 R@1·R@5·MRR을 출력 채널에 보여 준다. 오프라인 시험셋과 같은 기준이라 실사용 수치를 바로 비교할 수 있다.
- clangd Rerank: Rewrite launcher and restart clangd

제거하기 전에 **Disable**을 한 번 실행해 `clangd.path`를 되돌려 두는 것이 좋다(확장이 사라지면 런처 경로만 남는다).

## 알려진 한계

- 후보에 정답이 아예 없는 자리(새 이름을 짓는 곳 등)는 재정렬로 못 돕는다.
- `::` 뒤(네임스페이스 멤버)는 다른 자리보다 약하다. 보강 학습 진행 중.
- 서버 첫 요청은 커널 컴파일로 수 초 걸린다. 서버를 띄운 뒤 한 번 자동완성을 열어 워밍업하면 된다.
