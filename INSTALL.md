# Install (self-hosted, v0.3)

[한국어](INSTALL.ko.md)

clangd Rerank is two local model servers plus a VS Code extension. The models run only on your GPU, and your
code does not leave your machine.

| Part | Role | What it needs |
|---|---|---|
| **Sorter** server (port 8009) | reorders clangd's candidates | Kev framework + adapter `kev-0.8b-clangd-v5` (64 MB) |
| **Namer** server (port 8010) | name suggestions at declaration sites (optional) | llama.cpp + Qwen2.5-Coder-7B Q8_0 GGUF (8 GB) |
| VS Code extension | wraps clangd with the proxy | `clangd-rerank-0.3.0.vsix`, python3 |

## 1. Requirements

- Linux, WSL2, or a remote Linux host over Remote-SSH. **Windows-local is not supported yet** (the launcher is a bash script).
- NVIDIA GPU: 4 GB for Sorter alone, about 12 GB for Sorter + Namer 7B Q8_0 (16 GB card recommended). A driver that supports CUDA 13 (580 or newer).
- Python 3.12 (Namer wheel) and 3.13 (Kev), [uv](https://docs.astral.sh/uv/), git, curl.
- The [clangd extension](https://marketplace.visualstudio.com/items?itemName=llvm-vs-code-extensions.vscode-clangd) and a clangd binary already working in VS Code.
- `python3` for the proxy (standard library only; 3.9 or newer).

## 2. Get the repository and the model

```bash
git clone https://github.com/Bartimaeus-han/clangd-rerank.git
cd clangd-rerank
# The Sorter adapter is not in git. Download the release asset and unpack it under models/.
curl -LO https://github.com/Bartimaeus-han/clangd-rerank/releases/download/v0.3.0/kev-0.8b-clangd-v5.tar.gz
mkdir -p models && tar -xzf kev-0.8b-clangd-v5.tar.gz -C models   # → models/kev-0.8b-clangd-v5/
```

The Sorter base model (Qwen3.5-0.8B-Base, 1.6 GB) is downloaded from Hugging Face the first time the server starts.
The Namer model file is downloaded by hand in step 4.

## 3. Sorter server (reranking)

[Kev](https://github.com/jaredpalmer/kev) is not on PyPI. Install it from source (tested commit: `2074cc4`).

```bash
mkdir -p ext && git clone https://github.com/jaredpalmer/kev.git ext/kev
cd ext/kev && git checkout 2074cc4
uv sync --extra serve          # creates .venv with torch/transformers (a few minutes)
cd ../..
KEV_CUDA_GRAPHS=0 KEV_PREFIX_CACHE=0 ext/kev/.venv/bin/python -m kev.serve \
  --run models/kev-0.8b-clangd-v5 --port 8009 --host 127.0.0.1
```

`scripts/serve_kev.sh models/kev-0.8b-clangd-v5 8009` does the same and also sends warm-up requests (the first
requests compile kernels and take a few seconds, longer than the proxy's 0.4 s limit).
Check: `curl http://127.0.0.1:8009/v1/models` should answer.

## 4. Namer server (name suggestions, optional)

Runs Qwen2.5-Coder-7B (Q8_0) on llama.cpp. Median response 0.1 s, 0.05 s as you keep typing at the same spot.
It uses a separate venv from Kev (Python 3.12). The llama-cpp-python CUDA wheel is about 780 MB.

```bash
uv venv --python 3.12 ext/llama-venv
uv pip install --python ext/llama-venv/bin/python \
  https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.36-cu130/llama_cpp_python-0.3.36-py3-none-manylinux_2_35_x86_64.whl \
  "nvidia-cuda-runtime==13.0.*" "nvidia-cublas==13.*"
mkdir -p ext/gguf
curl -L -o ext/gguf/qwen2.5-coder-7b-q8_0.gguf \
  https://huggingface.co/ggml-org/Qwen2.5-Coder-7B-Q8_0-GGUF/resolve/main/qwen2.5-coder-7b-q8_0.gguf   # 8.1 GB
scripts/run_namer_llama.sh --port 8010      # default: ext/llama-venv + ext/gguf/qwen2.5-coder-7b-q8_0.gguf
```

It is ready when the log shows `gen server (llama.cpp) on 127.0.0.1:8010`. Pass another GGUF as the first argument
(`scripts/run_namer_llama.sh <file.gguf> --port 8010`). If GPU memory is tight, Q5_K_M
(`mradermacher/Qwen2.5-Coder-7B-GGUF`, 5.4 GB) is almost as accurate.

With 8 GB or less, or without CUDA 13, you can run the older HF server with Coder-1.5B (uses the Kev venv,
0.3 s per response, slightly less accurate):

```bash
ext/kev/.venv/bin/python scripts/gen_server.py --port 8010 --model Qwen/Qwen2.5-Coder-1.5B --beams 3
```

**Do not use Qwen2.5-Coder-3B** — it has a research-only license (1.5B and 7B are Apache-2.0).

To keep the servers running after you close the SSH session, start them with `setsid nohup ... > log 2>&1 < /dev/null &`.

## 5. VS Code extension

Download `clangd-rerank-0.3.0.vsix` from the [v0.3.0 release](https://github.com/Bartimaeus-han/clangd-rerank/releases/tag/v0.3.0), then:

```bash
code --install-extension clangd-rerank-0.3.0.vsix     # in a remote window it installs on the remote side
```

Settings (`settings.json`; remote settings for a remote window):

```jsonc
{
  "clangdRerank.enabled": true,                       // default true
  "clangdRerank.localServerUrl": "http://127.0.0.1:8009",
  "clangdRerank.generateUrl": "http://127.0.0.1:8010", // leave empty if you don't run Namer
  "clangdRerank.recordStats": true                     // log real-use accuracy (no code is stored)
}
```

When the extension is enabled it points `clangd.path` at a launcher script in its global storage and restarts clangd.
You should see `Rerank: local` in the status bar. Changing a setting rewrites the launcher and restarts clangd;
to do it by hand, run `clangd Rerank: Rewrite launcher and restart clangd`.

## 6. Check that it works

1. Open member completion in a C/C++ file, e.g. after `v.`. The first item should be pre-selected.
2. `clangd Rerank: Show proxy log` should show lines like `stage2 ... + stage3 ... top=[...]`.
3. With Namer running, open completion after `const std::string `. A `✦` name suggestion should be at the top.
4. `clangd Rerank: Show usage statistics` shows your real-use top-1 accuracy (with `recordStats` on).

## 7. Turning it off and uninstalling

- Pause: click the status bar item or run `clangd Rerank: Disable`. This restores your original `clangd.path`.
- Uninstall: **run Disable first**, then remove the extension. Otherwise `clangd.path` keeps pointing at a launcher that no longer exists and clangd will not start.
- Servers: just stop the processes.

## Troubleshooting

- Warning icon on `Rerank` in the status bar: check that `clangdRerank.pythonPath` (python3) runs.
- No reranking: if the proxy log keeps showing `rerank skipped: ... timeout`, the server is not warmed up yet. Open completion a few more times, or start it with `serve_kev.sh`.
- No `✦` items: `generateUrl` is empty or the Namer server is not running. Look for `gen skipped:` in the log.
- Out of GPU memory: switch Namer to Q5_K_M or HF 1.5B, or turn it off.
- With the servers stopped, completion can get *slower* than plain clangd (with WSL mirrored networking, a connection to a port nobody listens on hangs until the timeout instead of failing fast). Disable the extension when the servers are off.
