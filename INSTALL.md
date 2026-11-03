# 설치 안내 (셀프호스트, v0.2)

clangd Rerank 는 두 개의 로컬 모델 서버와 VS Code 확장으로 이루어진다. 모델은 내 GPU 에서만 돌고 코드는 밖으로 나가지 않는다.

| 구성 | 역할 | 필요한 것 |
|---|---|---|
| **Sorter** 서버 (포트 8009) | clangd 후보 재정렬 | Kev 프레임워크 + 어댑터 `kev-0.8b-clangd-v4` (63MB) |
| **Namer** 서버 (포트 8010) | 선언 자리 이름 제안 (선택) | `scripts/gen_server.py` + Qwen2.5-Coder-1.5B 또는 7B |
| VS Code 확장 | clangd 를 프록시로 감싼다 | `clangd-rerank-0.2.0.vsix`, python3 |

## 1. 요구 사항

- Linux, WSL2, 또는 macOS 원격(Remote-SSH). **Windows 로컬은 아직 지원하지 않는다** (런처가 bash 스크립트).
- NVIDIA GPU: Sorter 만이면 4GB, Namer 1.5B 까지 8GB, Namer 7B 4bit 까지 16GB.
- Python 3.12 또는 3.13, [uv](https://docs.astral.sh/uv/), git, curl.
- VS Code 에 [clangd 확장](https://marketplace.visualstudio.com/items?itemName=llvm-vs-code-extensions.vscode-clangd) 과 clangd 바이너리가 이미 동작할 것.
- 프록시용 `python3` (표준 라이브러리만 쓴다; 3.9 이상이면 된다).

## 2. 저장소와 모델 받기

```bash
git clone https://github.com/Bartimaeus-han/clangd-rerank.git
cd clangd-rerank
# Sorter 어댑터는 저장소에 없다. GitHub Release 자산 kev-0.8b-clangd-v4.tar.gz 를 받아 models/ 아래에 푼다.
mkdir -p models && tar -xzf kev-0.8b-clangd-v4.tar.gz -C models   # → models/kev-0.8b-clangd-v4/
```

기반 모델(Qwen3.5-0.8B-Base, Qwen2.5-Coder-1.5B/7B)은 서버를 처음 띄울 때 Hugging Face 에서 자동으로 받는다 (0.8B 1.6GB, 1.5B 3GB, 7B 15GB).

## 3. Sorter 서버 (재정렬)

[Kev](https://github.com/jaredpalmer/kev) 는 PyPI 에 없다. 소스로 설치한다 (검증한 커밋: `2074cc4`).

```bash
mkdir -p ext && git clone https://github.com/jaredpalmer/kev.git ext/kev
cd ext/kev && git checkout 2074cc4
uv sync --extra serve          # .venv 생성, torch/transformers 설치 (수 분)
cd ../..
KEV_CUDA_GRAPHS=0 KEV_PREFIX_CACHE=0 ext/kev/.venv/bin/python -m kev.serve \
  --run models/kev-0.8b-clangd-v4 --port 8009 --host 127.0.0.1
```

`scripts/serve_kev.sh models/kev-0.8b-clangd-v4 8009` 로 띄우면 워밍업 요청까지 보낸다 (첫 요청은 커널 컴파일로 몇 초 걸려 프록시의 0.4초 한도에 걸리기 때문).
확인: `curl http://127.0.0.1:8009/v1/models` 가 응답하면 된다.

## 4. Namer 서버 (이름 제안, 선택)

같은 venv 를 쓴다. 기본은 Coder-1.5B (추가 설치 없음, 응답 0.3초):

```bash
ext/kev/.venv/bin/python scripts/gen_server.py --port 8010 --model Qwen/Qwen2.5-Coder-1.5B --beams 3
```

정확도를 더 원하고 GPU 가 16GB 이상이면 7B 를 4비트로 (bitsandbytes 필요, 응답 0.6초):

```bash
uv pip install --python ext/kev/.venv/bin/python bitsandbytes
ext/kev/.venv/bin/python scripts/gen_server.py --port 8010 --model Qwen/Qwen2.5-Coder-7B --load-4bit --beams 3
```

로그에 `warmup co ...` 가 찍히면 준비된 것이다. **Qwen2.5-Coder-3B 는 쓰지 말 것** — 연구용 라이선스라 배포·상업 사용이 안 된다 (1.5B·7B 는 Apache-2.0).

서버를 SSH 세션과 무관하게 띄우려면 `setsid nohup ... > log 2>&1 < /dev/null &` 로 실행한다.

## 5. VS Code 확장

```bash
code --install-extension clangd-rerank-0.2.0.vsix     # 원격 창이면 원격 쪽에 설치된다
```

설정 (`settings.json`, 원격이면 원격 설정):

```jsonc
{
  "clangdRerank.enabled": true,                       // 기본 true
  "clangdRerank.localServerUrl": "http://127.0.0.1:8009",
  "clangdRerank.generateUrl": "http://127.0.0.1:8010", // Namer 를 안 띄우면 비워 둔다
  "clangdRerank.recordStats": true                     // 실사용 정확도 기록 (코드 본문은 저장 안 함)
}
```

확장이 켜지면 `clangd.path` 가 전역 저장소의 런처 스크립트로 바뀌고 clangd 가 다시 뜬다. 상태 표시줄에 `Rerank: local` 이 보이면 된다.
설정을 바꾸면 런처를 다시 쓰고 clangd 를 자동으로 재시작한다. 수동으로는 `clangd Rerank: Rewrite launcher and restart clangd`.

## 6. 동작 확인

1. C/C++ 파일에서 `v.` 처럼 멤버 자동완성을 연다. 첫 항목이 미리 선택돼 있어야 한다.
2. `clangd Rerank: Show proxy log` 에 `stage2 ... + stage3 ... top=[...]` 줄이 찍히면 재정렬이 되는 것이다.
3. Namer 를 켰으면 `const std::string ` 뒤에서 자동완성을 연다. 맨 위에 `✦ 이름 제안 (생성)` 항목이 뜬다.
4. `clangd Rerank: Show usage statistics` 로 실사용 1위 정답률을 본다 (`recordStats` 를 켰을 때).

## 7. 끄기·제거

- 잠시 끄기: 상태 표시줄 클릭 또는 `clangd Rerank: Disable`. `clangd.path` 를 원래 값으로 되돌린다.
- 제거: **먼저 Disable 을 실행**한 뒤 확장을 지운다. 확장이 사라지면 런처 경로만 남아 clangd 가 안 뜬다.
- 서버는 그냥 프로세스를 끝내면 된다.

## 문제가 있을 때

- `Rerank` 상태가 경고 아이콘: `clangdRerank.pythonPath` 의 python3 가 실행되는지 확인.
- 재정렬이 안 됨: 프록시 로그에 `rerank skipped: ... timeout` 이 반복되면 서버 워밍업이 안 된 것이다. 자동완성을 두세 번 더 열거나 `serve_kev.sh` 로 띄운다.
- ✦ 항목이 안 뜸: `generateUrl` 이 비었거나 Namer 서버가 안 떠 있는 경우. 로그의 `gen skipped:` 줄을 본다.
- GPU 메모리 부족: Namer 를 1.5B 로 내리거나 끈다.
