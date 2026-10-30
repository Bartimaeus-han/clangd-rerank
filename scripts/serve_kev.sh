#!/usr/bin/env bash
# 로컬 Kev 서버를 띄운다 (서빙 지연 측정, 프록시 연결용). 포트는 127.0.0.1에만 열린다.
# 사용: serve_kev.sh <체크포인트 경로 또는 Hub id> [포트=8009]
#   경로는 scratchpad 기준 상대 경로(ext/kev/runs/...)도, ext/kev 기준(runs/...)도, 절대 경로도 된다.
#   서버가 뜨면 워밍업 요청을 몇 번 보낸다(첫 요청은 커널 컴파일로 0.2~1초 걸려 프록시의 0.4초 제한에 걸리기 때문).
set -euo pipefail
RUN=${1:?체크포인트 경로가 필요합니다}
PORT=${2:-8009}
if [ -d "$RUN" ]; then RUN="$(cd "$RUN" && pwd)"; fi   # cd 전에 절대 경로로 바꿔 둔다
cd "$(dirname "$0")/ext/kev"
export KEV_CUDA_GRAPHS=${KEV_CUDA_GRAPHS:-0} KEV_PREFIX_CACHE=${KEV_PREFIX_CACHE:-0}
(
  for _ in $(seq 1 120); do curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/v1/models" && break; sleep 1; done
  for n in 8 29 60; do   # 후보 수별로 한 번씩 (프록시가 보내는 크기와 비슷하게)
    crit=$(python3 -c "import json,sys; n=int(sys.argv[1]); print(json.dumps({f'c{i}': f'item{i} -> detail' for i in range(n)}))" "$n")
    curl -s -m 30 -o /dev/null -w "warmup $n cands: %{http_code} %{time_total}s\n" -X POST "http://127.0.0.1:$PORT/v1/systemone" \
      -H 'content-type: application/json' -H 'authorization: Bearer local' \
      -d "{\"model\":\"kev-latest\",\"state\":\"#include <vector>\\nint main() {\\n  std::vector<int> v;\\n  v.\",\"questions\":{\"next\":{\"type\":\"choice\",\"instructions\":\"Pick the completion the programmer will choose next.\",\"criteria\":$crit}}}"
  done
) &
exec .venv/bin/python -m kev.serve --run "$RUN" --port "$PORT" --host 127.0.0.1
