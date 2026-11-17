# clangd Rerank

**A small local model that puts the right C/C++ completion at the top of clangd's list.**

[한국어](README.ko.md) · [Install](INSTALL.md) · [Research log](docs/RESEARCH.md) · MIT

<!-- DEMO GIF goes here: docs/demo.gif (see the launch checklist) -->

clangd already knows *what* you can type. It is much worse at guessing *which* item you want: on fresh,
unseen C++ code the pre-selected item is correct only 28% of the time when you have typed nothing yet.
clangd Rerank keeps clangd's candidates exactly as they are and only changes their **order**, using a
0.8B model fine-tuned for this one job. The top item becomes correct 79% of the time.

It also adds an optional **Namer**: at the spot where you declare a new variable, parameter or function, it
suggests 1–3 names as normal dropdown items (marked `✦`). No inline ghost text.

Everything runs on your own GPU. Your code does not leave your machine.

## Results

Measured on 38 GitHub repositories **created after 2026-03-01** (after the base model was released), 21 topics
(games, embedded, Qt, emulators, ...), permissive licenses only, zero file overlap with the training data.
"Top-1" = the pre-selected item is the identifier the original author actually wrote next.

**Sorter (reranking)** — 2,087 completion sites, 5,647 queries

| What you have typed | clangd order | clangd Rerank |
|---|---|---|
| nothing (`obj.`, `ns::`, start of a word) | 28.3% | **79.3%** |
| 1 character | 59.6% | **90.8%** |
| 2 characters | 68.3% | **91.5%** |
| sites with same-name variants (`std::string` vs `std::pmr::string`) | 32.7% | **84.7%** |
| all queries | 52.5% | **87.9%** |

Latency: about 50 ms for the model, 70–90 ms end to end through the proxy (RTX 4080 SUPER).
If the model does not answer within 400 ms, you get clangd's normal list, so it never blocks typing.

**Namer (names at declaration sites)** — 357 sites

| What you have typed | exact name at #1 | in the top 5 |
|---|---|---|
| nothing | 47.6% | 63.0% |
| 1 character | 63.6% | 75.4% |
| 2 characters | 68.9% | 82.1% |

Median response 0.10 s for a new site, 0.05 s as you keep typing (p90 0.15 s).
For reference, a cloud LLM (Claude Haiku 5.5) given the same context scored 47.9 / 59.7 / 62.7%.

What these numbers do **not** cover: they only count sites where the right identifier is in clangd's list,
and they simulate writing code top to bottom (nothing after the cursor). Full method and every intermediate
result: [docs/RESEARCH.md](docs/RESEARCH.md) (Korean).

## How it works

```
VS Code ── clangd extension ── proxy ──────────────────── clangd
                                 │  completion response
                                 ├─ stage 2: LightGBM ranker (pure Python, a few ms) → top 60
                                 ├─ stage 3: Sorter, Qwen3.5-0.8B + LoRA (local server) → final order
                                 └─ declaration site? → Namer, Qwen2.5-Coder-7B via llama.cpp → ✦ items
```

- The VS Code extension points `clangd.path` at a small launcher, so the proxy sits between the editor and
  the real clangd. It rewrites only `sortText` in completion responses. Nothing else in clangd changes.
- **Sorter** reads the 40 lines before the cursor and scores the candidates. It was trained on about 110k
  examples from roughly 240 open-source projects (24 libraries, 219 applications) plus competitive-programming
  solutions. Since v5 it chooses between items with the same name but different insert text, so
  `string` no longer gives you `std::pmr::string` first.
- **Namer** runs only where a new name is being declared (detected from the text before the cursor).
  Decoding is constrained to valid identifiers that start with what you typed, with a name-level beam
  search on llama.cpp's low-level API.

## Requirements

- Linux, WSL2, or a remote Linux host (Remote-SSH). **Windows-local is not supported yet.**
- NVIDIA GPU: about 4 GB for Sorter alone, about 12 GB for Sorter + Namer (16 GB card recommended).
- The [clangd extension](https://marketplace.visualstudio.com/items?itemName=llvm-vs-code-extensions.vscode-clangd)
  already working in VS Code.

This is a self-hosted early release: you start two model servers yourself. See **[INSTALL.md](INSTALL.md)**.
The extension is not on the Marketplace yet; the `.vsix` is on the
[Releases page](https://github.com/Bartimaeus-han/clangd-rerank/releases).

## How this was built

I built this with heavy use of an AI coding assistant (Claude Code) for writing code, running experiments
and drafting documents. The problem, the design choices (reorder only, dropdown instead of inline
suggestions, measuring on post-release repositories) and the decisions about what to keep or drop were mine,
and every number above comes from scripts in this repository.

## Models and licenses

- Code: MIT.
- Sorter base: [Qwen3.5-0.8B-Base](https://huggingface.co/Qwen) (Apache-2.0) + LoRA adapter from this project,
  served with [Kev](https://github.com/jaredpalmer/kev).
- Namer: [Qwen2.5-Coder-7B](https://huggingface.co/Qwen/Qwen2.5-Coder-7B) (Apache-2.0), GGUF from
  `ggml-org/Qwen2.5-Coder-7B-Q8_0-GGUF`, served with [llama.cpp](https://github.com/ggml-org/llama.cpp)
  (via llama-cpp-python).
